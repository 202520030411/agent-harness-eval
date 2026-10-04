"""回归门（E9）：固定题目清单上，改动版 B 相对基线 A 的题级通过率不得下降超过阈值；否则退出码非零。

用法：agenteval regress <baseline_job> <candidate_job> --tasks regression_tasks.txt [--max-drop-pp 34]
锚题（基线 3/3 通过）默认容忍 1 次失败（k=3 时 33.3 pp），修复目标题不得回退到 0。
"""
from __future__ import annotations

from pathlib import Path

from agenteval.report.stats import per_task_rate
from agenteval.schemas import TrialRecord


def gate(a: list[TrialRecord], b: list[TrialRecord], tasks: list[str], max_drop_pp: float = 34.0) -> dict:
    ra = per_task_rate([(t.task_name, t.passed) for t in a if t.status in ("ok", "agent_timeout")])
    rb = per_task_rate([(t.task_name, t.passed) for t in b if t.status in ("ok", "agent_timeout")])
    rows, failed = [], []
    for task in tasks:
        if task not in ra or task not in rb:
            rows.append({"task": task, "status": "MISSING"}); failed.append(task); continue
        drop = 100 * (ra[task] - rb[task])
        ok = drop <= max_drop_pp and not (ra[task] > 0 and rb[task] == 0 and ra[task] >= 2 / 3)
        rows.append({"task": task, "A": ra[task], "B": rb[task], "drop_pp": round(drop, 1), "status": "OK" if ok else "REGRESSED"})
        if not ok:
            failed.append(task)
    return {"rows": rows, "failed": failed, "passed": not failed}


def render(r: dict) -> str:
    L = ["| 题 | A | B | 下降 pp | 状态 |", "|---|---|---|---|---|"]
    for x in r["rows"]:
        if x["status"] == "MISSING":
            L.append(f"| {x['task']} | — | — | — | MISSING |")
        else:
            L.append(f"| {x['task']} | {x['A']:.2f} | {x['B']:.2f} | {x['drop_pp']:+.1f} | {x['status']} |")
    L.append("")
    L.append("GATE PASSED" if r["passed"] else f"GATE FAILED: {r['failed']}")
    return "\n".join(L) + "\n"
