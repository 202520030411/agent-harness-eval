"""规则 × 判官交叉表、判官主标签分布（按 TB 三大类）、onset 统计、人工标注表。"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from agenteval.judge.attribution import LABELS
from agenteval.schemas import TrialRecord

HUMAN_LABELS = [k for k in LABELS if k not in ("CANNOT_JUDGE",)]


def load_judge(path: Path) -> dict[str, dict]:
    rows = {}
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line); rows[r["trial_id"]] = r
    return rows


def crosstab(trials: list[TrialRecord], judge: dict[str, dict]) -> dict:
    failed = [t for t in trials if not t.passed and t.status in ("ok", "agent_timeout")]
    by_class = Counter(); by_primary = Counter(); ct = defaultdict(Counter); onsets = []
    for t in failed:
        j = judge.get(t.trial_id)
        prim = j["judge_primary"] if j else "NOT_JUDGED"
        by_primary[prim] += 1
        by_class[LABELS.get(prim, ("NONE",))[0]] += 1
        rules = [l.name for l in t.labels if l.source == "RULE" and l.kind == "failure"] or ["(none)"]
        for r in rules:
            ct[r][prim] += 1
        if j and j.get("judge_onset") is not None and t.n_episodes:
            onsets.append((j["judge_onset"], t.n_episodes))
    onset_frac = [o / n for o, n in onsets if n]
    return {"n_failed": len(failed), "judge_primary": dict(by_primary.most_common()), "judge_tb_class": dict(by_class.most_common()),
            "rule_x_judge": {r: dict(c) for r, c in ct.items()},
            "onset_median_frac": (sorted(onset_frac)[len(onset_frac) // 2] if onset_frac else None),
            "onset_first_third_share": (sum(1 for f in onset_frac if f <= 1 / 3) / len(onset_frac) if onset_frac else None)}


def render(ct: dict) -> str:
    L = [f"## 判官主标签（{ct['n_failed']} 条失败）", ""]
    for k, v in ct["judge_primary"].items():
        L.append(f"- {k}: {v}（{100 * v / ct['n_failed']:.0f}%）")
    L += ["", "## 按 TB 三大类", ""] + [f"- {k}: {v}" for k, v in ct["judge_tb_class"].items()]
    L += ["", f"## onset：判官标的起始轮位于轨迹的中位相对位置 {ct['onset_median_frac'] and round(ct['onset_median_frac'], 2)}；"
          f"前 1/3 就出问题的占 {ct['onset_first_third_share'] and round(100 * ct['onset_first_third_share'])}%（Failure as a Process：失败起得早）", ""]
    L += ["## 规则标签 × 判官主标签", "", "| 规则 | " + " | ".join(sorted({p for c in ct['rule_x_judge'].values() for p in c})) + " |"]
    cols = sorted({p for c in ct["rule_x_judge"].values() for p in c})
    L.append("|---|" + "---|" * len(cols))
    for r, c in sorted(ct["rule_x_judge"].items(), key=lambda kv: -sum(kv[1].values())):
        L.append(f"| {r} | " + " | ".join(str(c.get(p, "")) for p in cols) + " |")
    return "\n".join(L) + "\n"


def write_labeling_sheet(trials: list[TrialRecord], judge: dict[str, dict], out: Path, jobs_dir: str) -> int:
    """人工标注表（第 4 天）。人不看判官的答案：判官列放最后，标注时折叠。"""
    failed = [t for t in trials if not t.passed and t.status in ("ok", "agent_timeout")]
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trial_id", "task", "attempt", "turns", "status", "rule_labels", "verifier_tail_120",
                    "human_primary", "human_onset", "human_secondary", "human_notes", "clarity_intent_0_3", "clarity_target_0_3",
                    "__judge_primary(不要先看)", "__judge_onset"])
        for t in failed:
            j = judge.get(t.trial_id, {})
            rules = ";".join(l.name for l in t.labels if l.source == "RULE" and l.kind == "failure")
            vt = (t.metadata.get("verifier_stdout_tail") or "").strip().replace("\n", " ")[-120:]
            w.writerow([t.trial_id, t.task_name, t.attempt, t.n_episodes, t.status, rules, vt, "", "", "", "", "", "",
                        j.get("judge_primary", ""), j.get("judge_onset", "")])
    return len(failed)
