"""PSP 式开头规则（D-072 试点；arXiv 2609.29051 “From Self-Distillation to Self-Practice”）。
gpt-6-sol 读一道题上 Qwen 的几次失败（每次最后几轮的命令与终端输出 + 隐藏测试的结果）和只给它看的知识（参考解 + 隐藏测试，
与 D-069 Teacher 同一份 teacher_knowledge.json），写 3–6 条行动规则；规则放在题面最前面，原版 Qwen 带着规则重做。
与 D-067 的区别：D-067 没看失败记录；与 D-069 的区别：D-069 在做题过程中实时插话，这里只在开头给一次。
硬规矩（同 D-069）：不许有代码、命令、文件内容、具体期望值、测试原文；每条 ≤ 35 词、总计 ≤ 180 词（= D-069 一条 rollout 最多 3 × 60 词）；
与参考解或测试有 8 词连续重合的规则丢掉；不合格重试一次，仍不合格 → 这道题不带规则照跑（算在方法头上，不挑题）。
用法（服务器）：( set -a; . ~/.secrets.env; set +a; PYTHONPATH=. .venv/bin/python train/synth/psp_rules.py \
    --tasks-dir /root/work/train/synth_split/train_hard --knowledge /root/work/train/teacher_knowledge.json \
    --jobs /root/work/jobs/qroll-h2-synth-train /root/work/jobs/qroll-h2-synth-train-hint \
    --dst /root/work/train/synth_split/train_psp --hints-out /root/work/train/hints_psp.json --rules-out /root/work/train/psp_rules.json )
"""
from __future__ import annotations

import argparse
import collections
import functools
import json
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from terminus2_patches.teacher import render_view  # noqa: E402
from tools.qarm_report import _agent_steps, _obs, _shell_cmds  # noqa: E402
from train.synth.skill_hints import grams  # noqa: E402

PRICE_IN, PRICE_OUT = 2.0e-6, 1.0e-5          # gpt-6-sol，美元 / token（同 generate.py）
MIN_RULES, MAX_RULES, RULE_WORDS, TOTAL_WORDS = 3, 6, 35, 180
HEADER = "Notes from a reviewer who studied earlier failed attempts at this task (read them before you start):"

SYSTEM = f"""You coach a junior AI agent that solves tasks in a Linux terminal. It attempted the task below several times and failed every time. You see the task, privileged material the agent cannot see (a reference solution and the hidden tests that grade its work), and for each failed attempt its last commands with their terminal output and the result of the hidden tests.

First work out why the attempts failed. Then write {MIN_RULES} to {MAX_RULES} short action rules that the agent will read before its next attempt. Each rule must target a mistake you actually saw in the failed attempts: what to do differently, and what to check before declaring the task complete. At most {RULE_WORDS} words per rule. Never include code, shell commands, file contents, regular expressions, SQL, exact expected values, or the text of the tests.

Reply with the rules only, in this format:
<skills>
1. ...
2. ...
</skills>"""

_RULE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)\s*$")


def parse_rules(text: str) -> tuple[list[str], str | None]:
    """<skills> 里的编号规则 → (规则, 不合格原因)。单条超长的丢掉；按顺序收到总词数上限为止；不足 3 条或带代码块 → 不合格。"""
    m = re.search(r"<skills>(.*?)</skills>", text or "", re.S)
    if not m:
        return [], "no_skills_block"
    if "```" in m.group(1):
        return [], "contains_code_block"
    rules, total = [], 0
    for line in m.group(1).splitlines():
        x = _RULE.match(line)
        if not x:
            continue
        r = " ".join(x.group(1).split())
        n = len(r.split())
        if n > RULE_WORDS or total + n > TOTAL_WORDS or len(rules) == MAX_RULES:
            continue
        rules.append(r); total += n
    return (rules, None) if len(rules) >= MIN_RULES else (rules, f"too_few_rules({len(rules)})")


def drop_leaks(rules: list[str], privileged: str) -> tuple[list[str], int]:
    """与参考解 / 测试有 8 词连续重合的规则丢掉（同 D-067 的检查）。"""
    g = grams(privileged)
    keep = [r for r in rules if not (grams(r) & g)]
    return keep, len(rules) - len(keep)


def render_block(rules: list[str]) -> str:
    return HEADER + "\n<skills>\n" + "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1)) + "\n</skills>\n\n"


def attempt_view(d: Path, max_turns: int = 8, max_out_chars: int = 800, verifier_chars: int = 1500) -> str:
    """一次失败：最后几轮的命令与终端输出（不含 Qwen 的思考，同 D-069）+ 隐藏测试结果的结尾。"""
    try:
        steps = _agent_steps(json.load(open(d / "agent" / "trajectory.json")))
    except Exception:  # noqa: BLE001
        steps = []
    turns = [{"turn": i, "commands": _shell_cmds(s), "output": _obs(s)} for i, s in enumerate(steps, 1)]
    ver = d / "verifier" / "test-stdout.txt"
    tail = ver.read_text(errors="ignore")[-verifier_chars:] if ver.exists() else "(no test output)"
    return f"{len(steps)} turns in total, last {min(max_turns, len(steps))} shown.\n{render_view(turns, max_turns, max_out_chars)}\n[hidden test result]\n{tail}"


@functools.lru_cache(maxsize=None)
def _failed_index(job: str) -> dict[str, list[Path]]:
    """{题目短名: 失败 trial 目录}（判分 < 1；基础设施报错的不算）。按 result.json 里的 task_name 认题：
    Harbor 会把目录名里的题名截到 32 个字符（2026-09-27 试点第一次跑时按目录名找，51 题里 47 题一次失败都没找到）。"""
    idx = collections.defaultdict(list)
    for f in sorted(Path(job).glob("*__*/result.json")):
        r = json.load(open(f))
        exc = (r.get("exception_info") or {}).get("exception_type")
        if exc and exc not in ("AgentTimeoutError", "VerifierTimeoutError"):
            continue
        if ((((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")) or 0) < 1:
            idx[r["task_name"].split("/")[-1]].append(f.parent)
    return idx


def failed_trials(task: str, jobs: list[str], max_n: int) -> list[Path]:
    """这道题在给定几轮里的失败 trial，按轮次顺序取前 max_n 个。"""
    return [d for j in jobs for d in _failed_index(str(j)).get(task, [])][:max_n]


def knowledge_text(task_dir: Path) -> str:
    """只给 gpt-6-sol 看的知识：参考解 + 隐藏测试（与 D-069 的 teacher_knowledge.json 同一格式）。"""
    sol = (task_dir / "solution" / "solve.sh").read_text()[:9000]
    tests = (task_dir / "tests" / "test_outputs.py").read_text()[:9000]
    return f"REFERENCE SOLUTION (solve.sh):\n{sol}\n\nHIDDEN TESTS (test_outputs.py):\n{tests}"


def rules_for_task(task: str, instruction: str, knowledge: str, fails: list[Path], new_client, over_budget=lambda: False) -> tuple[dict, dict]:
    """一道题：gpt-6-sol 读失败记录写规则，不合格重试一次。返回 (记录, 本题用掉的 token)。new_client() 每次调用给一个新的 JudgeClient。"""
    used = {"prompt_tokens": 0, "completion_tokens": 0}
    rec = {"task": task, "n_failed_seen": len(fails), "rules": [], "reason": None, "leaks_dropped": 0, "tries": 0}
    if not fails:
        rec["reason"] = "no_failed_attempts_found"
        return rec, used
    views = "\n\n".join(f"=== FAILED ATTEMPT {i} ===\n{attempt_view(d)}" for i, d in enumerate(fails, 1))
    user = (f"TASK (what the agent sees):\n{instruction.strip()}\n\n"
            f"PRIVILEGED (only you can see this; never quote it):\n{knowledge.strip()}\n\n{views}")
    for retry in (False, True):
        if over_budget():
            rec["reason"] = "budget_stop"
            return rec, used
        note = f"\n\nYOUR PREVIOUS REPLY WAS REJECTED ({rec['reason']}). Follow the format and the rules exactly." if retry else ""
        cli = new_client()
        try:
            text = cli.complete(SYSTEM, user + note)
        except Exception as e:  # noqa: BLE001
            text, rec["reason"] = "", f"api_error:{type(e).__name__}"
        used["prompt_tokens"] += cli.usage["prompt_tokens"]; used["completion_tokens"] += cli.usage["completion_tokens"]
        rec["tries"] += 1
        if not text:
            continue
        rules, why = parse_rules(text)
        if not why:
            rules, n = drop_leaks(rules, knowledge)
            rec["leaks_dropped"] += n
            why = None if len(rules) >= MIN_RULES else f"too_few_after_leak_check({len(rules)})"
        rec["rules"], rec["reason"] = ([], why) if why else (rules, None)
        if not why:
            break
    return rec, used


def main(a) -> None:
    from agenteval.judge.client import JudgeClient
    src = Path(a.tasks_dir)
    know = json.load(open(a.knowledge))
    tasks = a.tasks.split(",") if a.tasks else sorted(p.name for p in src.iterdir() if p.is_dir())
    if missing := [t for t in tasks if t not in know]:
        raise SystemExit(f"no knowledge for {missing[:5]}")
    lock = threading.Lock()
    spend = {"in": 0, "out": 0}

    def usd() -> float:
        return spend["in"] * PRICE_IN + spend["out"] * PRICE_OUT

    def over() -> bool:
        with lock:
            return usd() > a.max_usd

    def one(t: str) -> dict:
        rec, used = rules_for_task(t, (src / t / "instruction.md").read_text(), know[t], failed_trials(t, a.jobs, a.max_attempts),
                                   lambda: JudgeClient(a.model, reasoning_effort="medium", max_tokens=a.max_tokens), over)
        with lock:
            spend["in"] += used["prompt_tokens"]; spend["out"] += used["completion_tokens"]
        return rec

    with ThreadPoolExecutor(a.concurrency) as ex:
        recs = list(ex.map(one, tasks))
    hints = {r["task"]: render_block(r["rules"]) for r in recs if r["rules"]}
    if a.dst:
        dst = Path(a.dst)
        if dst.exists():
            shutil.rmtree(dst)
        for r in recs:
            shutil.copytree(src / r["task"], dst / r["task"])
            if r["task"] in hints:
                f = dst / r["task"] / "instruction.md"
                f.write_text(hints[r["task"]] + f.read_text())
    if a.hints_out:
        Path(a.hints_out).write_text(json.dumps(hints, indent=1, ensure_ascii=False))
    Path(a.rules_out).write_text(json.dumps(recs, indent=1, ensure_ascii=False))
    bad = [(r["task"], r["reason"]) for r in recs if not r["rules"]]
    print(f"{len(tasks)} tasks: rules for {len(hints)}, without rules {len(bad)} {bad[:5]}; "
          f"failed attempts seen per task {min(r['n_failed_seen'] for r in recs)}–{max(r['n_failed_seen'] for r in recs)}; "
          f"leaky rules dropped {sum(r['leaks_dropped'] for r in recs)}; spend ${usd():.2f}")
    print(f"PSP_RULES_SPEND_USD {usd():.4f}")
    for t in list(hints)[:2]:
        print(f"--- {t}\n{hints[t].strip()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", required=True)
    ap.add_argument("--knowledge", required=True)
    ap.add_argument("--jobs", nargs="+", required=True)
    ap.add_argument("--tasks", default="", help="逗号分隔；不给就是 --tasks-dir 下的全部题")
    ap.add_argument("--dst", default="", help="带规则的题目目录；不给就只写 --rules-out（RL 循环用）")
    ap.add_argument("--hints-out", default="")
    ap.add_argument("--rules-out", required=True)
    ap.add_argument("--model", default="gpt-6-sol")
    ap.add_argument("--max-attempts", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--max-usd", type=float, default=8.0, help="累计花费超过就不再发新调用")
    ap.add_argument("--concurrency", type=int, default=8)
    main(ap.parse_args())
