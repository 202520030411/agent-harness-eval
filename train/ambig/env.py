"""进程内的多轮环境：工作区 = 一个 dict（路径 → 内容），三个动作，最多 MAX_TURNS 轮。

动作用 JSON 表示（不依赖各家工具调用模板），每轮模型输出一个 JSON：
  {"thought": "...", "action": "search", "query": "separator"}     # 在所有文件里按关键词搜（不区分大小写），等价于 grep -rin
  {"thought": "...", "action": "list_dir", "path": "."}
  {"thought": "...", "action": "read_file", "path": "services/billing/config.yaml"}
  {"thought": "...", "action": "submit", "answer": "..."}
奖励 = 提交且答案正确（generator.check_answer）；另记机制指标：提交前是否读过证据文件。
"""
from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, field

from generator import Task, check_answer

MAX_TURNS = 15
MAX_SEARCH_HITS = 20
MAX_READ_CHARS = 4000

SYSTEM_PROMPT = """You are a software engineer working in a project workspace. You can only interact with it through actions.
Reply with exactly ONE JSON object per turn and nothing else:
{"thought": "<brief reasoning>", "action": "search", "query": "<text to find in any file, case-insensitive>"}
{"thought": "<brief reasoning>", "action": "list_dir", "path": "<directory, e.g. .>"}
{"thought": "<brief reasoning>", "action": "read_file", "path": "<file path>"}
{"thought": "<brief reasoning>", "action": "submit", "answer": "<your final answer as a string>"}
You have at most 15 turns. `submit` ends the task; only the submitted answer is graded."""


def first_prompt(task: Task) -> str:
    return f"Task: {task.instruction}\n\nThe project files are in the workspace root `.`."


def parse_action(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except Exception:  # noqa: BLE001
        return None
    return obj if isinstance(obj, dict) and obj.get("action") in ("search", "list_dir", "read_file", "submit") else None


def _norm(p: str) -> str:
    p = posixpath.normpath((p or ".").strip().lstrip("/"))
    return "" if p in (".", "") else p


@dataclass
class Episode:
    task: Task
    messages: list = field(default_factory=list)
    reads: list = field(default_factory=list)
    done: bool = False
    reward: float = 0.0
    submitted: str | None = None
    n_invalid: int = 0
    searched_hits: set = field(default_factory=set)
    first_evidence_turn: int | None = None
    n_search: int = 0

    def __post_init__(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": first_prompt(self.task)}]

    @property
    def turns(self) -> int:
        return sum(1 for m in self.messages if m["role"] == "assistant")

    @property
    def read_evidence(self) -> bool:
        """看到证据 = 读过证据文件，或搜索结果里出现了证据文件的行（有了 search 之后，光看命中行也能拿到约定）。"""
        ev = self.task.evidence_path
        return ev is not None and (_norm(ev) in self.reads or _norm(ev) in self.searched_hits)

    def _mark_evidence(self):
        if self.first_evidence_turn is None and self.read_evidence:
            self.first_evidence_turn = self.turns

    def step(self, assistant_text: str) -> str | None:
        """记录模型回复并执行动作；返回下一条观察（None 表示结束）。"""
        self.messages.append({"role": "assistant", "content": assistant_text})
        act = parse_action(assistant_text)
        files = self.task.files
        if act is None:
            self.n_invalid += 1
            obs = "ERROR: reply with exactly one JSON object with an `action` of search, list_dir, read_file or submit."
        elif act["action"] == "submit":
            self.submitted = str(act.get("answer", ""))
            self.reward = 1.0 if check_answer(self.task, self.submitted) else 0.0
            self.done = True
            return None
        elif act["action"] == "search":
            q = str(act.get("query", "")).strip().lower()
            hits = []
            if q:
                for p in sorted(files):
                    for i, line in enumerate(files[p].split("\n"), 1):
                        if q in line.lower():
                            hits.append(f"{p}:{i}: {line[:200]}")
            self.n_search += 1
            if hits:
                self.searched_hits.update(h.split(":", 1)[0] for h in hits)
                self._mark_evidence()
            obs = "\n".join(hits[:MAX_SEARCH_HITS]) + (f"\n[... {len(hits) - MAX_SEARCH_HITS} more]" if len(hits) > MAX_SEARCH_HITS else "") \
                if hits else f"no matches for {act.get('query')!r}"
        elif act["action"] == "list_dir":
            d = _norm(act.get("path", "."))
            prefix = d + "/" if d else ""
            entries = sorted({(p[len(prefix):].split("/")[0] + ("/" if "/" in p[len(prefix):] else ""))
                              for p in files if p.startswith(prefix)})
            obs = "\n".join(entries) if entries else f"ERROR: no such directory: {act.get('path')}"
        else:
            p = _norm(act.get("path", ""))
            if p in files:
                self.reads.append(p)
                self._mark_evidence()
                c = files[p]
                obs = c if len(c) <= MAX_READ_CHARS else c[:MAX_READ_CHARS] + "\n[... truncated]"
            else:
                obs = f"ERROR: no such file: {act.get('path')}"
        if self.turns >= MAX_TURNS:
            self.done = True
            return None
        obs = f"OBSERVATION:\n{obs}"
        self.messages.append({"role": "user", "content": obs})
        return obs

    def record(self) -> dict:
        return {"task_id": self.task.task_id, "family": self.task.family, "needs_evidence": self.task.needs_evidence,
                "evidence_path": self.task.evidence_path, "reward": self.reward, "read_evidence": self.read_evidence,
                "turns": self.turns, "invalid": self.n_invalid, "submitted": self.submitted, "answer": self.task.answer,
                "first_evidence_turn": self.first_evidence_turn, "n_search": self.n_search,
                "turn_cap": self.done and self.submitted is None,
                "difficulty": self.task.meta.get("difficulty", "easy"),
                "messages": self.messages}
