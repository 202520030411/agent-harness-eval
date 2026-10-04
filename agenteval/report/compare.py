"""两个 Harbor job（基线 A vs 改动 B）的配对比较：题级通过率差 + 区间 + McNemar + 资源指标差 + 逐题翻转表。"""
from __future__ import annotations

from statistics import mean

from agenteval.report.stats import paired_compare
from agenteval.schemas import TrialRecord


def _evaluable(ts: list[TrialRecord]) -> list[TrialRecord]:
    return [t for t in ts if t.status in ("ok", "agent_timeout")]


def _label_rate(ts: list[TrialRecord], name: str) -> float | None:
    failed = [t for t in ts if not t.passed]
    if not failed:
        return None
    return sum(1 for t in failed if any(l.name == name and l.kind == "failure" and l.value not in (False, 0, None) for l in t.labels)) / len(failed)


def compare_jobs(a: list[TrialRecord], b: list[TrialRecord], name_a: str, name_b: str, n_boot: int = 10000) -> dict:
    a, b = _evaluable(a), _evaluable(b)
    pc = paired_compare([(t.task_name, t.passed) for t in a], [(t.task_name, t.passed) for t in b], n_boot=n_boot)
    def agg(ts):
        return {"pass_mean": mean(1.0 if t.passed else 0.0 for t in ts) if ts else None,
                "turns": mean(t.n_episodes for t in ts) if ts else None,
                "tokens_in": mean(t.tokens_in for t in ts) if ts else None,
                "tokens_out": mean(t.tokens_out for t in ts) if ts else None,
                "cached_share": (sum(t.tokens_cached for t in ts) / sum(t.tokens_in for t in ts)) if sum(t.tokens_in for t in ts) else None,
                "cost": mean(t.cost for t in ts) if ts else None,
                "wall_sec": mean(t.wall_clock_sec for t in ts if t.wall_clock_sec) if any(t.wall_clock_sec for t in ts) else None,
                "timeouts": sum(1 for t in ts if t.status == "agent_timeout"),
                "n": len(ts)}
    A, B = agg(a), agg(b)
    labels = ["PREMATURE_COMPLETION", "BUDGET_EXHAUSTED", "TRUNCATED_READ", "COMMAND_NOT_FOUND", "POLLING", "STUCK_AT_PROMPT", "LOOP", "FORMAT"]
    lab = {l: (_label_rate(a, l), _label_rate(b, l)) for l in labels}
    patched = {}
    for key in ("auditor_calls", "auditor_rejections", "first_turn_rejections", "stuck_reminders", "adaptive_n",
                "adaptive_sentinel_finished", "adaptive_sentinel_timeout", "adaptive_prompt_detected", "adaptive_waited_sec_total"):
        vals = [(t.metadata.get("patched") or {}).get(key) for t in b]
        vals = [v for v in vals if isinstance(v, (int, float))]
        if vals:
            patched[key] = sum(vals)
    return {"A": name_a, "B": name_b, "paired": pc, "aggA": A, "aggB": B, "label_rates_A_B": lab, "patched_B": patched}


def render_compare(r: dict) -> str:
    pc, A, B = r["paired"], r["aggA"], r["aggB"]
    def pct(x): return "—" if x is None else f"{100*x:.1f}%"
    def d(x, y, f="{:.2f}"): return "—" if x is None or y is None else f.format(y - x)
    L = [f"# {r['B']} vs {r['A']}（配对，{pc['n_tasks']} 题）", "",
         f"- Δ通过率（题级平均）：**{pc['delta_pp']:+.1f} pp**，bootstrap 95% 区间 [{pc['ci95_pp'][0]:+.1f}, {pc['ci95_pp'][1]:+.1f}]",
         f"- 题级翻转：A过B不过 {pc['flips_A_pass_B_fail']}，A不过B过 {pc['flips_A_fail_B_pass']}；McNemar p = {pc['mcnemar_p']:.3f}",
         f"- trial 级通过率：{pct(A['pass_mean'])} → {pct(B['pass_mean'])}；超时 {A['timeouts']} → {B['timeouts']}（n {A['n']} → {B['n']}）",
         f"- 平均轮数 {A['turns']:.1f} → {B['turns']:.1f}（{d(A['turns'], B['turns'], '{:+.1f}')}）· 墙钟 {A['wall_sec'] and round(A['wall_sec'])} → {B['wall_sec'] and round(B['wall_sec'])} s",
         f"- 输入 token/trial {A['tokens_in']:,.0f} → {B['tokens_in']:,.0f}（{d(A['tokens_in'], B['tokens_in'], '{:+,.0f}')}）· 输出 {A['tokens_out']:,.0f} → {B['tokens_out']:,.0f} · 缓存命中 {pct(A['cached_share'])} → {pct(B['cached_share'])}",
         f"- 成本/trial {A['cost']:.3f} → {B['cost']:.3f}（{d(A['cost'], B['cost'], '{:+.3f}')}）", ""]
    if r["patched_B"]:
        L += ["- fork 统计（B 合计）：" + ", ".join(f"{k}={v}" for k, v in r["patched_B"].items()), ""]
    L += ["## 失败标签占失败 trial 的比例（A → B）", ""]
    for k, (x, y) in r["label_rates_A_B"].items():
        if x or y:
            L.append(f"- {k}: {pct(x)} → {pct(y)}")
    L += ["", "## 逐题（A 通过率 → B 通过率）", "", "| 题 | A | B | 变化 |", "|---|---|---|---|"]
    for t, (x, y) in sorted(pc["per_task"].items(), key=lambda kv: kv[1][1] - kv[1][0]):
        arrow = "↑" if y > x else ("↓" if y < x else "=")
        L.append(f"| {t} | {x:.2f} | {y:.2f} | {arrow} |")
    return "\n".join(L) + "\n"
