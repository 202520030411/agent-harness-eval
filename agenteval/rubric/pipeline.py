"""Rubric 提炼 + 偏序验证（multi_agent_task_gen/PROJECT.md §5.2–5.3 的复现）。

配对：同一题，强侧 = 通过的轨迹（强模型或同模型通过的 attempt），弱侧 = 失败的轨迹。
1. Rubric Writer（强模型判官）：对比一对轨迹，写出 3–6 条可打 0/1 的 rubric 条目（好行为 ↔ bad pattern）。
2. 打分（便宜判官）：每条 rubric 给两侧所有轨迹各打 0/1。
3. 偏序验证（纯函数）：一条 rubric 只有在"强侧平均分 > 弱侧平均分 + margin"时才可信；否则丢弃。
   通过验证的 rubric 既筛题也筛轨迹（结果对但过程差的不进 SFT）。
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from statistics import mean

from agenteval.judge.client import JudgeClient
from agenteval.judge.views import render_trajectory
from agenteval.schemas import TrialRecord

WRITER_SYSTEM = """You compare two runs of a terminal coding agent on the SAME task: one that PASSED the hidden tests and one that FAILED.
Write 3-6 rubric items: each is a binary (yes/no) criterion about the agent's BEHAVIOR that the passing run satisfied and the failing run did not
(e.g. "verified the output file format against the instruction before finishing", "checked the ELF load address before assuming a base").
Items must be checkable from a transcript alone, task-specific but phrased so a grader can apply them to any run of this task, and must not
mention which run passed. Also name the bad pattern each item targets in a few words.
Output ONLY a JSON list: [{"id": "R1", "criterion": "...", "bad_pattern": "..."}, ...]"""

SCORER_SYSTEM = """You grade a terminal coding-agent transcript against binary rubric items. For each item answer 1 if the transcript clearly
satisfies it, else 0. Judge only from commands and terminal output; the agent's own claims are not evidence.
Output ONLY a JSON object mapping item id to 0 or 1."""


def pairs_by_task(strong: list[TrialRecord], weak: list[TrialRecord]) -> dict[str, tuple[list[TrialRecord], list[TrialRecord]]]:
    s_ok = defaultdict(list); w_bad = defaultdict(list)
    for t in strong:
        if t.passed: s_ok[t.task_name].append(t)
    for t in weak:
        if not t.passed and t.status in ("ok", "agent_timeout"): w_bad[t.task_name].append(t)
    return {k: (s_ok[k], w_bad[k]) for k in s_ok if k in w_bad}


def write_rubric(writer: JudgeClient, instruction: str | None, strong: TrialRecord, weak: TrialRecord) -> list[dict]:
    user = ("TASK INSTRUCTION:\n" + (instruction or "(n/a)") + "\n\n=== RUN A (passed) ===\n" + render_trajectory(strong, None, max_steps=40, blind=True)
            + "\n\n=== RUN B (failed) ===\n" + render_trajectory(weak, None, max_steps=40, blind=True))
    raw = writer.complete(WRITER_SYSTEM, user)
    try:
        s, e = raw.find("["), raw.rfind("]")
        items = json.loads(raw[s:e + 1])
        return [i for i in items if isinstance(i, dict) and i.get("criterion")]
    except Exception:
        return []


def score_trial(scorer: JudgeClient, items: list[dict], t: TrialRecord) -> dict[str, int]:
    rub = "\n".join(f"{i['id']}: {i['criterion']}" for i in items)
    user = "RUBRIC:\n" + rub + "\n\nTRANSCRIPT:\n" + render_trajectory(t, None, max_steps=60, blind=True)
    raw = scorer.complete(SCORER_SYSTEM, user)
    try:
        s, e = raw.find("{"), raw.rfind("}")
        d = json.loads(raw[s:e + 1])
        return {i["id"]: (1 if str(d.get(i["id"], 0)).strip() in ("1", "true", "True") else 0) for i in items}
    except Exception:
        return {i["id"]: 0 for i in items}


def validate_partial_order(scores_strong: list[dict[str, int]], scores_weak: list[dict[str, int]], margin: float = 0.25) -> dict[str, dict]:
    """纯函数：每条 rubric 的强侧均分、弱侧均分、是否通过偏序验证。"""
    out = {}
    ids = set().union(*[s.keys() for s in scores_strong + scores_weak]) if (scores_strong or scores_weak) else set()
    for i in sorted(ids):
        a = [s.get(i, 0) for s in scores_strong]; b = [s.get(i, 0) for s in scores_weak]
        ma, mb = (mean(a) if a else 0.0), (mean(b) if b else 0.0)
        out[i] = {"strong_mean": ma, "weak_mean": mb, "gap": ma - mb, "valid": (ma - mb) >= margin and ma > 0.5}
    return out


def run_rubric_pipeline(writer: JudgeClient, scorer: JudgeClient, instruction_for, strong: list[TrialRecord], weak: list[TrialRecord],
                        max_tasks: int | None = None) -> dict:
    result = {}
    pairs = pairs_by_task(strong, weak)
    for n, (task, (s_ok, w_bad)) in enumerate(sorted(pairs.items())):
        if max_tasks and n >= max_tasks: break
        items = write_rubric(writer, instruction_for(task), s_ok[0], w_bad[0])
        if not items:
            result[task] = {"items": [], "note": "writer produced no items"}; continue
        ss = [score_trial(scorer, items, t) for t in s_ok]
        sw = [score_trial(scorer, items, t) for t in w_bad]
        val = validate_partial_order(ss, sw)
        result[task] = {"items": items, "validation": val, "n_strong": len(s_ok), "n_weak": len(w_bad),
                        "valid_items": [i["id"] for i in items if val.get(i["id"], {}).get("valid")]}
    return result
