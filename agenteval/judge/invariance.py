"""判官不变性测试（M3，借 False Success 论文的发现）：只改写模型的自述措辞（更自信 / 更犹豫），命令和终端输出一字不动，
再让同一个判官判，看主标签翻转率。翻转率高 = 判官在看措辞而不是看证据。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from agenteval.judge.attribution import judge_trial
from agenteval.judge.client import JudgeClient
from agenteval.schemas import TrialRecord

STYLE = {
    "confident": "Rewrite the following agent status message so it sounds highly confident and conclusive (e.g. 'Verified and complete.'), "
                 "without adding or removing any factual claim about files, commands, or results. Output only the rewritten text.",
    "hesitant": "Rewrite the following agent status message so it sounds uncertain and tentative (e.g. 'I think this might be done, but I am not sure'), "
                "without adding or removing any factual claim about files, commands, or results. Output only the rewritten text.",
}


def perturb(t: TrialRecord, rewriter: JudgeClient, style: str, max_steps: int = 12) -> TrialRecord:
    t2 = copy.deepcopy(t)
    steps = [s for s in t2.agent_steps if s.message.strip()]
    # 只改最后 max_steps 轮的自述（判官最关注的部分），控制成本
    for s in steps[-max_steps:]:
        try:
            s.message = rewriter.complete(STYLE[style], s.message[:1500])
        except RuntimeError as e:   # 改写模型拒答（内容策略）→ 保留原文，记一下
            print(f"[rewriter refused, kept original] {t.trial_id} step {s.step_id}: {str(e)[:120]}")
    return t2


def run_invariance(judge: JudgeClient, rewriter: JudgeClient, trials: list[TrialRecord], instruction_for, out: Path,
                   styles=("confident", "hesitant")) -> dict:
    rows = []
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text("")
    for t in trials:
        ins = instruction_for(t.task_name)
        base = next((l for l in judge_trial(judge, t, ins) if l.name == "primary_failure"), None)
        row = {"trial_id": t.trial_id, "task": t.task_name, "base": base.value if base else "CANNOT_JUDGE"}
        for st in styles:
            t2 = perturb(t, rewriter, st)
            lab = next((l for l in judge_trial(judge, t2, ins) if l.name == "primary_failure"), None)
            row[st] = lab.value if lab else "CANNOT_JUDGE"
        rows.append(row)
        print(row, flush=True)
        with out.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    flips = {st: sum(1 for r in rows if r[st] != r["base"]) for st in styles}
    summary = {"n": len(rows), "flips": flips, "flip_rate": {st: flips[st] / len(rows) if rows else None for st in styles}}
    print(summary)
    return summary
