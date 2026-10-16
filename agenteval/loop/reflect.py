"""反思：把观察到的失败模式分到三个队列——harness 去改、训练去补、人去查。确定性的，不调模型。

- harness 队列：先验归 HARNESS / MIXED、且在开发集上足够常见的模式 → 交给提议模型出候选；
- 训练队列：先验归 MODEL 的模式 → 进训练数据目标（"共同进化"的模型一侧）；
- 人工队列：先验 UNKNOWN 的模式、作弊嫌疑、每次都做不出来的题（可能是题目缺陷，也可能是能力）。
每个模式附上"已经试过哪些开关、结果如何"，避免提议模型重复已知的失败。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def reflect(table: list[dict[str, Any]], rows: list[dict[str, Any]], history: list[dict[str, Any]] | None = None,
            min_rate: float = 0.05, min_n: int = 5) -> dict[str, Any]:
    history = history or []
    harness, model, human = [], [], []
    for m in table:
        common = m["rate"] >= min_rate and m["n"] >= min_n
        tried = [h for h in history if any(lever in (h.get("switches") or "") for lever in m["levers"])]
        item = {**m, "tried": [{"id": h.get("id"), "switches": h.get("switches"), "model": h.get("model"),
                                "pass_delta_pp": h.get("pass_delta_pp"), "verdict": h.get("manual_verdict")} for h in tried]}
        if m["mode"] == "integrity_suspect":
            if m["n"]:
                human.append({**item, "why": "possible reward hacking: read the trajectories"})
            continue
        if not common:
            continue
        if m["prior"] in ("HARNESS", "MIXED"):
            harness.append(item)
        elif m["prior"] == "MODEL":
            model.append(item)
        else:
            human.append({**item, "why": "attribution unknown: needs a cross-harness or cross-model comparison"})
    harness.sort(key=lambda x: -x["share_of_failures"])
    model.sort(key=lambda x: -x["share_of_failures"])

    per_task: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        if not r.get("infra"):
            per_task[r["task"]].append(bool(r.get("passed")))
    never = sorted(t for t, v in per_task.items() if len(v) >= 3 and not any(v))       # 至少 3 次可用才算"每次都做不出来"
    learnable = sorted(t for t, v in per_task.items() if any(v) and not all(v))
    if never:
        human.append({"mode": "never_solved", "label": "每次都做不出来的题", "n": len(never), "tasks": never,
                      "why": "task defect or capability gap: audit a sample with the 'only edit the instruction' test before using them"})
    # 训练队列目前只是一张清单（写进 reflect.json / reflect.md），没有代码接到训练线：要人手动带过去
    return {"harness_targets": harness, "model_targets": model, "human_review": human,
            "task_difficulty": {"never_solved": len(never), "mixed_outcome": len(learnable),
                                "always_solved": sum(1 for v in per_task.values() if v and all(v)), "n_tasks": len(per_task)}}
