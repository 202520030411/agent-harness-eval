"""报告图：从 summary.json / trials.jsonl / judge.jsonl 画（1）通过率-成本 Pareto，（2）各臂失败类别剖面，（3）终止方式表。
只依赖 matplotlib；输入目录里文件名形如 <job>.summary.json / <job>.trials.jsonl / <job>.judge.jsonl。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

TB_CLASS = {"SPEC_MISINTERPRETATION": "Coherence", "GOAL_DRIFT": "Coherence", "ACKNOWLEDGED_BUT_IGNORED": "Coherence",
            "INSUFFICIENT_VERIFICATION": "Verification", "PREMATURE_COMPLETION": "Verification",
            "BUDGET_EXHAUSTED": "Execution", "CAPABILITY": "Execution", "LOOP": "Execution", "POLLING": "Execution",
            "TASK_UNDERSPECIFIED": "Task", "CANNOT_JUDGE": "Unknown"}


def _setup_font():
    import matplotlib
    matplotlib.use("Agg")
    import logging; logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    from matplotlib import font_manager
    have = {f.name for f in font_manager.fontManager.ttflist}
    pref = [f for f in ["Hiragino Sans GB", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei"] if f in have]
    matplotlib.rcParams["font.family"] = pref + ["DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False


def _load(d: Path, job: str):
    s = json.loads((d / f"{job}.summary.json").read_text())
    jp = d / f"{job}.judge.jsonl"
    judge = [json.loads(l)["judge_primary"] for l in jp.read_text().splitlines() if l.strip()] if jp.exists() else []
    return s, judge


def pareto(d: Path, jobs: dict[str, str], out: Path, title: str, cost_unit: str = "元/trial"):
    _setup_font()
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for job, label in jobs.items():
        s, _ = _load(d, job)
        x, y = s["cost_per_trial"], 100 * s["mean_over_trials (capability-evaluable)"]
        ax.scatter(x, y, s=60); ax.annotate(label, (x, y), textcoords="offset points", xytext=(5, 4), fontsize=8)
    ax.set_xlabel(f"成本（{cost_unit}）"); ax.set_ylabel("trial 级通过率 %"); ax.set_title(title); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def failure_profile(d: Path, jobs: dict[str, str], out: Path, title: str):
    _setup_font()
    import matplotlib.pyplot as plt
    classes = ["Coherence", "Verification", "Execution", "Task", "Unknown"]
    data = {}
    for job, label in jobs.items():
        s, judge = _load(d, job)
        n = s["n_trials"]
        c = Counter(TB_CLASS.get(j, "Unknown") for j in judge)
        data[label] = [100 * c[k] / n for k in classes]   # 占全部 trial 的比例，臂间可比
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    bottom = [0] * len(data)
    for i, k in enumerate(classes):
        vals = [data[l][i] for l in data]
        ax.bar(list(data), vals, bottom=bottom, label=k); bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_ylabel("失败 trial 占比 %（按判官主标签的 TB 大类）"); ax.set_title(title); ax.legend(fontsize=8)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right"); fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def termination_table(d: Path, jobs: dict[str, str]) -> str:
    L = ["| 臂 | trial | 通过 | 超时 | 平均轮数 | 首轮打回 | 审计打回 | 空等待轮 | 解析错轮 |", "|---|---|---|---|---|---|---|---|---|"]
    for job, label in jobs.items():
        s, _ = _load(d, job); p = s.get("patched_totals", {})
        L.append(f"| {label} | {s['n_trials']} | {100*s['mean_over_trials (capability-evaluable)']:.1f}% | {s['status_counts'].get('agent_timeout', 0)} | "
                 f"{s['mean_turns']:.1f} | {p.get('first_turn_rejections', 0)} | {p.get('auditor_rejections', 0)} | {s['polling_turns_total']} | {s['parse_error_turns_total']} |")
    return "\n".join(L) + "\n"
