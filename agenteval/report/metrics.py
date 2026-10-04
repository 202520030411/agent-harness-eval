"""四级指标 + 题级聚合 + 成本（借 FirstCoder summarize.py 的分层与 Inspect 的 reducer 词汇）。"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean

from agenteval.schemas import TrialRecord


def summarize(trials: list[TrialRecord]) -> dict:
    n = len(trials)
    env_ok = [t for t in trials if t.status != "setup_failed"]
    capability_evaluable = [t for t in trials if t.status in ("ok", "agent_timeout")]  # 排除 ENVIRONMENT（不变量 3）
    explicit = [t for t in trials if t.reward is not None]
    passes = [t for t in explicit if t.passed]

    by_task: dict[str, list[TrialRecord]] = defaultdict(list)
    for t in capability_evaluable:
        by_task[t.task_name].append(t)
    task_mean = {k: mean(1.0 if x.passed else 0.0 for x in v) for k, v in by_task.items()}
    task_pass_at_k = {k: float(any(x.passed for x in v)) for k, v in by_task.items()}

    fail_labels = Counter()
    for t in capability_evaluable:
        if not t.passed:
            for l in t.labels:
                if l.kind == "failure" and l.value not in (False, 0, None):
                    fail_labels[l.name + (f"={l.value}" if l.data_type == "CATEGORICAL" else "")] += 1
    n_fail = sum(1 for t in capability_evaluable if not t.passed)

    def num(name):
        vals = [l.value for t in capability_evaluable for l in t.labels if l.name == name and l.data_type == "NUMERIC"]
        return (sum(vals), mean(vals)) if vals else (0, 0.0)

    tok_in = sum(t.tokens_in for t in capability_evaluable)
    tok_cached = sum(t.tokens_cached for t in capability_evaluable)
    return {
        "n_trials": n,
        "n_tasks": len({t.task_name for t in trials}),
        "env_success_rate": len(env_ok) / n if n else None,
        "agent_setup_success_rate": len([t for t in trials if t.status not in ("setup_failed",)]) / len(env_ok) if env_ok else None,
        "reward_only_pass_rate": len(passes) / len(explicit) if explicit else None,
        "end_to_end_pass_rate": len(passes) / n if n else None,
        "mean_over_trials (capability-evaluable)": mean(1.0 if t.passed else 0.0 for t in capability_evaluable) if capability_evaluable else None,
        "pass_at_k (task level)": mean(task_pass_at_k.values()) if task_pass_at_k else None,
        "status_counts": dict(Counter(t.status for t in trials)),
        "mean_turns": mean(t.n_episodes for t in capability_evaluable) if capability_evaluable else None,
        "mean_wall_clock_sec": mean(t.wall_clock_sec for t in capability_evaluable if t.wall_clock_sec) if any(t.wall_clock_sec for t in capability_evaluable) else None,
        "tokens_in_total": tok_in,
        "tokens_out_total": sum(t.tokens_out for t in capability_evaluable),
        "cached_share": tok_cached / tok_in if tok_in else None,
        "cost_total": sum(t.cost for t in capability_evaluable),
        "cost_per_trial": mean(t.cost for t in capability_evaluable) if capability_evaluable else None,
        "polling_turns_total": num("polling_turns")[0],
        "parse_error_turns_total": num("parse_error_turns")[0],
        "truncated_observations_total": num("truncated_observations")[0],
        "compactions_total": num("compactions")[0],
        "n_failed_capability_evaluable": n_fail,
        "failure_label_counts": dict(fail_labels.most_common()),
        "failure_label_rates": {k: v / n_fail for k, v in fail_labels.items()} if n_fail else {},
        "patched_totals": _patched_totals(capability_evaluable),
        "task_mean": dict(sorted(task_mean.items())),
        "task_pass_at_k": dict(sorted(task_pass_at_k.items())),
    }


def _patched_totals(ts: list[TrialRecord]) -> dict:
    out: dict = {}
    for t in ts:
        p = (t.metadata or {}).get("patched") or {}
        for k, v in p.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = out.get(k, 0) + v
    return out


def render_markdown(s: dict, title: str) -> str:
    def pct(x): return "—" if x is None else f"{100*x:.1f}%"
    lines = [f"# {title}", "",
             f"- trials: {s['n_trials']}（{s['n_tasks']} 题）; status: {s['status_counts']}",
             f"- 环境成功 {pct(s['env_success_rate'])} · agent 安装成功 {pct(s['agent_setup_success_rate'])} · reward-only 通过 {pct(s['reward_only_pass_rate'])} · 端到端通过 {pct(s['end_to_end_pass_rate'])}",
             f"- mean（trial 级）{pct(s['mean_over_trials (capability-evaluable)'])} · pass@k（题级）{pct(s['pass_at_k (task level)'])}",
             f"- 平均轮数 {s['mean_turns'] and round(s['mean_turns'],1)} · 平均墙钟 {s['mean_wall_clock_sec'] and round(s['mean_wall_clock_sec'])} s · 每 trial 成本 {s['cost_per_trial'] and round(s['cost_per_trial'],3)}（配置单位）· 总成本 {round(s['cost_total'],2)}",
             f"- 输入 token {s['tokens_in_total']:,} · 输出 {s['tokens_out_total']:,} · 缓存命中 {pct(s['cached_share'])}",
             f"- 空等待轮 {s['polling_turns_total']} · 解析错误轮 {s['parse_error_turns_total']} · 截断观察 {s['truncated_observations_total']} · 压缩 {s['compactions_total']}",
             (f"- fork stats total: {s['patched_totals']}" if s.get('patched_totals') else ""),
             "", f"## 失败标签（{s['n_failed_capability_evaluable']} 条失败 trial，可多标签）", ""]
    for k, v in s["failure_label_counts"].items():
        lines.append(f"- {k}: {v}（{pct(s['failure_label_rates'][k])}）")
    lines += ["", "## 题级", "", "| 题 | mean | pass@k |", "|---|---|---|"]
    for k in s["task_mean"]:
        lines.append(f"| {k} | {s['task_mean'][k]:.2f} | {s['task_pass_at_k'][k]:.0f} |")
    return "\n".join(lines) + "\n"
