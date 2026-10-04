"""实时 Teacher 提示（D-069；做法参考实习时用过的 teacher-guided rollout）。

Student（Qwen）每做完几轮、或刚宣布完成时，Teacher（gpt-6-sol）看：题面 + 只给它看的“知识”（参考解 + 隐藏测试）
+ Student 最近执行的命令和终端输出（看不到 Student 的思考），决定要不要插一句针对性的短提示。
硬规矩（与实习版一致）：提示条数与长度有上限；格式不对 / 超长 → 不说话；Teacher 连续出错 → 熔断、不再调用，
Student 照常做完；判分器完全不动（提示不可能“造出”通过）。
本文件只放纯函数与小状态（可单测）；网络调用在 agent.py 里经 asyncio.to_thread 调 agenteval 的 JudgeClient。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

MARK = "[Reviewer note] "

SYSTEM = """You supervise a junior AI agent that is solving a task in a Linux terminal. You see the task, privileged material the agent cannot see (a reference solution and the hidden tests that will grade its work), and the agent's recent commands with their terminal output (not its private reasoning).

Decide whether to interrupt the agent with ONE short hint right now. Deliver a hint only if at least one is true:
- the agent is heading in a wrong direction, or its current work would fail a hidden test;
- it is stuck: repeating the same command, looping on the same error, or making no progress;
- it ignored an error or a mismatch that is visible in the output;
- it is about to declare the task complete (or just did) while the work is still wrong or unverified.

The hint must name the concrete problem in the agent's current work and where to look (for example which requirement its output violates, or which error it ignored), in at most {max_words} words. Never include code, shell commands, file contents, exact expected values, or the text of the tests. If the agent is on track, do not interrupt.

Reply with JSON only: {{"deliver": true or false, "hint": "..."}}"""


@dataclass
class HintDecision:
    deliver: bool
    text: str | None
    drop_reason: str | None


def _json_block(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_hint(text: str, max_words: int) -> HintDecision:
    """`{"deliver": bool, "hint": str}`；格式不对、空、超长、带代码块 → 不说话。"""
    obj = _json_block(text)
    if not obj or not isinstance(obj.get("deliver"), bool):
        return HintDecision(False, None, "malformed")
    if not obj["deliver"]:
        return HintDecision(False, None, "teacher_abstained")
    hint = obj.get("hint")
    if not isinstance(hint, str) or not hint.strip():
        return HintDecision(False, None, "empty_hint")
    hint = " ".join(hint.split())
    if len(hint.split()) > max_words:
        return HintDecision(False, None, f"over_word_cap({len(hint.split())}>{max_words})")
    if "```" in hint:
        return HintDecision(False, None, "contains_code_block")
    return HintDecision(True, hint, None)


def render_view(turns: list[dict], max_turns: int = 10, max_out_chars: int = 1200) -> str:
    """Student 最近几轮：执行的命令 + 终端输出（截断）。不含 analysis / plan（Student 的思考）。"""
    parts = []
    for t in turns[-max_turns:]:
        cmds = "\n".join("$ " + k.rstrip("\n") for k in t.get("commands", []) if k.strip()) or "(no command; waited or declared completion)"
        out = t.get("output", "") or ""
        if len(out) > max_out_chars:
            out = out[:max_out_chars // 2] + "\n...[truncated]...\n" + out[-max_out_chars // 2:]
        parts.append(f"--- turn {t['turn']}\n{cmds}\n[output]\n{out}")
    return "\n".join(parts)


def build_user(instruction: str, knowledge: str, view: str, moment: str) -> str:
    return (f"TASK (what the agent sees):\n{instruction.strip()}\n\n"
            f"PRIVILEGED (only you can see this; never quote it):\n{knowledge.strip()}\n\n"
            f"MOMENT: {moment}\n\nAGENT'S RECENT TURNS (commands and terminal output):\n{view}")


class Breaker:
    """连续失败 max_failures 次后打开，之后不再调用 Teacher；一次成功清零。"""

    def __init__(self, max_failures: int = 3):
        self.max_failures, self.consecutive = max_failures, 0

    @property
    def open(self) -> bool:
        return self.consecutive >= self.max_failures

    def record(self, ok: bool) -> None:
        self.consecutive = 0 if ok else self.consecutive + 1
