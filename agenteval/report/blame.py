"""归责二维表（taxonomy.md §4）：对每个失败模式 p，看"换模型（同 harness）"和"换 harness（同模型）"各自是否让 p 的发生率变化 ≥ δ。

发生率定义：p 在该配置全部可评 trial 里出现的比例（不是失败里的比例，否则总数变化会干扰）。
输入是四个 job 的 TrialRecord 列表：弱模型基线 / 弱模型改 harness / 强模型基线 / 强模型改 harness（后者可缺）。
模式来源：规则标签（kind=failure）+ 判官主标签（可选）。粒度是模式级，不是单条 trial 的因果。
"""
from __future__ import annotations

from collections import Counter

from agenteval.schemas import TrialRecord

ENV_TASK = {"SETUP_FAILED", "VERIFIER_FAILURE", "AGENT_RUNTIME_ERROR", "PROVIDER_REFUSAL", "TASK_UNDERSPECIFIED"}


def pattern_rates(trials: list[TrialRecord], judge: dict[str, str] | None = None) -> tuple[dict[str, float], int]:
    ev = [t for t in trials if t.status in ("ok", "agent_timeout")]
    c: Counter = Counter()
    for t in ev:
        names = {l.name for l in t.labels if l.kind == "failure"}
        if judge and t.trial_id in judge:
            names.add(judge[t.trial_id])
        for n in names:
            c[n] += 1
    n = max(len(ev), 1)
    return {k: v / n for k, v in c.items()}, len(ev)


def blame_table(weak_base, weak_mod, strong_base, strong_mod=None, delta: float = 0.08, judges=None) -> list[dict]:
    judges = judges or {}
    rb, nb = pattern_rates(weak_base, judges.get("weak_base"))
    rm, nm = pattern_rates(weak_mod, judges.get("weak_mod"))
    rs, ns = pattern_rates(strong_base, judges.get("strong_base"))
    rsm, nsm = (pattern_rates(strong_mod, judges.get("strong_mod")) if strong_mod else ({}, 0))
    rows = []
    for p in sorted(set(rb) | set(rm) | set(rs) | set(rsm), key=lambda k: -rb.get(k, 0)):
        d_model = rb.get(p, 0) - rs.get(p, 0)          # 换模型：弱→强，正数=强模型少犯
        d_harness = rb.get(p, 0) - rm.get(p, 0)        # 换 harness：基线→改动，正数=改动减少
        m, h = abs(d_model) >= delta, abs(d_harness) >= delta
        blame = "MIXED" if (m and h) else "MODEL" if m else "HARNESS" if h else ("ENVIRONMENT/TASK" if p in ENV_TASK else "UNKNOWN(<δ)")
        rows.append({"pattern": p, "weak_base": rb.get(p, 0), "weak_mod": rm.get(p, 0), "strong_base": rs.get(p, 0),
                     "strong_mod": rsm.get(p, 0) if strong_mod else None,
                     "d_model_pp": round(100 * d_model, 1), "d_harness_pp": round(100 * d_harness, 1), "blame": blame})
    return rows


def render(rows: list[dict], names: dict, delta: float) -> str:
    L = [f"# 归责表（模式级；δ = {100*delta:.0f} pp；发生率 = 出现该模式的 trial / 全部可评 trial）", "",
         f"- 弱模型基线：{names['weak_base']}；弱模型改动：{names['weak_mod']}；强模型基线：{names['strong_base']}"
         + (f"；强模型改动：{names['strong_mod']}" if names.get("strong_mod") else ""), "",
         "| 模式 | 弱·基线 | 弱·改动 | 强·基线 | 强·改动 | Δ换模型 | Δ换harness | 归责 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        sm = "—" if r["strong_mod"] is None else f"{100*r['strong_mod']:.0f}%"
        L.append(f"| {r['pattern']} | {100*r['weak_base']:.0f}% | {100*r['weak_mod']:.0f}% | {100*r['strong_base']:.0f}% | {sm} | {r['d_model_pp']:+.0f} | {r['d_harness_pp']:+.0f} | **{r['blame']}** |")
    L += ["", "读法：Δ换模型 = 弱基线 − 强基线（正数 = 强模型少犯，说明是模型能力问题）；Δ换harness = 弱基线 − 弱改动（正数 = harness 改动减少了它）。",
          "两者都 ≥ δ 记 MIXED，只有前者 MODEL，只有后者 HARNESS；都 < δ 的按标签类别归 ENVIRONMENT/TASK 或 UNKNOWN。"]
    return "\n".join(L) + "\n"
