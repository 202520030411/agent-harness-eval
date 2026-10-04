"""H17 的预注册分析（写于开跑前，2026-09-26，D-049）。跑完只执行，不改口径。

三张表：
  1. 按预定义子集（全集 / 模糊 14 / 清晰 27）：基线 vs 条件式的题级配对 Δ + bootstrap 95% 区间、超时、轮数、成本
  2. 开关机制：实跑开启率（trial 级、按子集）、题级多数票与 14 道的重合、评分耗时、超时/出错次数、评分 token
  3. 按实际开关结果分组（开 / 关）的配对 Δ：关组只剩评分耗时的代价，开组等于契约效果
判定（HYPOTHESES.md H17 修订版）：清晰题 Δ ≥ −3（E4p v1 为 −7.4）且模糊题 Δ ≥ +5 → 成立；全集 Δ 不作为条件。
用法（服务器）：.venv/bin/python tools/h17_report.py --out /root/work/reports/h17/report.md
"""
from __future__ import annotations

import argparse
import collections
import statistics as st
from pathlib import Path

from agenteval.adapters.harbor import load_job
from agenteval.report.stats import paired_compare

ROOT = Path(__file__).resolve().parent.parent
E4P_V1 = {"amb": 7.1, "clear": -7.4}   # E4p 契约 v1 的参照值（experiments/README.md）


def passed(t) -> bool:
    return t.reward is not None and t.reward >= 1


def arm_summary(ts) -> dict:
    n = len(ts)
    return {"n": n, "pass": 100 * sum(passed(t) for t in ts) / max(1, n),
            "timeouts": sum(t.status == "agent_timeout" for t in ts),
            "turns": st.mean(t.n_episodes for t in ts) if ts else 0,
            "cost": st.mean(t.cost for t in ts) if ts else 0}


def compare(base, cond, keep) -> dict:
    b = [t for t in base if keep(t.task_name)]; c = [t for t in cond if keep(t.task_name)]
    r = paired_compare([(t.task_name, passed(t)) for t in b], [(t.task_name, passed(t)) for t in c])
    return {"n_tasks": r["n_tasks"], "delta": r["delta_pp"], "ci": r["ci95_pp"], "base": arm_summary(b), "cond": arm_summary(c)}


def fmt_row(name, r) -> str:
    lo, hi = r["ci"]
    return (f"| {name} | {r['n_tasks']} | {r['base']['pass']:.1f}% | {r['cond']['pass']:.1f}% | **{r['delta']:+.1f}** [{lo:+.1f}, {hi:+.1f}] "
            f"| {r['base']['timeouts']} → {r['cond']['timeouts']} | {r['base']['turns']:.1f} → {r['cond']['turns']:.1f} "
            f"| {r['base']['cost']:.3f} → {r['cond']['cost']:.3f} |")


def main(a):
    base, cond = load_job(Path(a.baseline)), load_job(Path(a.conditional))
    amb = {x.strip() for x in (ROOT / "experiments/task_list_ambiguous.txt").read_text().splitlines() if x.strip()}
    lines = ["# H17 条件式契约：结果（预注册分析脚本 tools/h17_report.py 输出）", "",
             f"基线 {a.baseline}（{len(base)} trials）vs 条件式 {a.conditional}（{len(cond)} trials）", "",
             "## 1. 按预定义子集", "",
             "| 口径 | 题数 | 基线 | 条件式 | Δ 题级配对 [95% CI] | 超时 | 轮数 | 成本/trial |", "|---|---|---|---|---|---|---|---|"]
    subsets = {"全集": lambda t: True, "模糊题（clarity ≥2）": lambda t: t in amb, "清晰题": lambda t: t not in amb}
    res = {k: compare(base, cond, f) for k, f in subsets.items()}
    for k, r in res.items():
        lines.append(fmt_row(k, r))
    d_amb, d_clear = res["模糊题（clarity ≥2）"]["delta"], res["清晰题"]["delta"]
    verdict = "成立" if (d_clear >= -3 and d_amb >= 5) else "不成立"
    lines += ["", f"判定：清晰题 Δ {d_clear:+.1f}（E4p v1 {E4P_V1['clear']:+.1f}，门槛 ≥ −3）；模糊题 Δ {d_amb:+.1f}（E4p v1 {E4P_V1['amb']:+.1f}，门槛 ≥ +5）→ **{verdict}**。"
              "区间含 0 的子集只记方向。", ""]

    # ---- 2. 开关机制
    gates = [(t, (t.metadata.get("patched") or {}).get("contract_gate")) for t in cond]
    missing = [t.trial_id for t, g in gates if not g]
    gates = [(t, g) for t, g in gates if g]
    on_by = collections.defaultdict(list)
    for t, g in gates:
        on_by[t.task_name].append(bool(g.get("on")))
    task_on = {k for k, v in on_by.items() if sum(v) * 2 > len(v)}
    lat = [g["latency_sec"] for _, g in gates if g.get("latency_sec") is not None]
    errs = [(t.task_name, g.get("error")) for t, g in gates if g.get("error")]
    a_tr = [g for t, g in gates if t.task_name in amb]; c_tr = [g for t, g in gates if t.task_name not in amb]
    lines += ["## 2. 开关机制", "",
              f"- 有开关记录的 trial：{len(gates)}/{len(cond)}" + (f"（缺失：{missing[:5]}）" if missing else ""),
              f"- 开启率（trial 级）：模糊题 {sum(g['on'] for g in a_tr)}/{len(a_tr)}，清晰题 {sum(g['on'] for g in c_tr)}/{len(c_tr)}"
              f"（离线预检 90% / 27%；预注册门槛 ≥80% / ≤35%）",
              f"- 题级多数票判为模糊 {len(task_on)} 道，与 14 道重合 {len(task_on & amb)}/14；误开清晰题：{sorted(task_on - amb)}；漏开模糊题：{sorted(amb - task_on)}",
              f"- 评分耗时：中位 {st.median(lat):.0f} s、p90 {sorted(lat)[int(0.9 * len(lat))]:.0f} s、最长 {max(lat):.0f} s" if lat else "- 评分耗时：无数据",
              f"- 评分出错/超时（按清晰题处理）：{len(errs)} 次 {errs[:5]}",
              (f"- 评分 token：输入均值 {st.mean(g['tokens_in'] for _, g in gates):.0f}、输出均值 {st.mean(g['tokens_out'] for _, g in gates):.0f}，"
               f"成本均值 {st.mean(g['cost_usd'] for _, g in gates):.4f}/trial") if gates else "- 评分 token：无数据", ""]

    # ---- 3. 按实际开关分组
    lines += ["## 3. 按实际开关结果分组（题级多数票）", "",
              "| 组 | 题数 | 基线 | 条件式 | Δ [95% CI] | 超时 | 轮数 | 成本/trial |", "|---|---|---|---|---|---|---|---|"]
    for name, keep in (("开关开（走契约）", lambda t: t in task_on), ("开关关（走上游 + 评分耗时）", lambda t: t not in task_on)):
        try:
            lines.append(fmt_row(name, compare(base, cond, keep)))
        except ValueError:
            lines.append(f"| {name} | 0 | — | — | — | — | — | — |")
    lines += ["", "读法：关组的 Δ 是评分调用本身的代价（应接近 0、不低于 −3）；开组的 Δ 应接近 E4p 契约在模糊题上的 +7。", ""]
    md = "\n".join(lines)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(md)
    print(md); print(f"[written] {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", default="/root/work/jobs/h17-baseline")
    p.add_argument("--conditional", default="/root/work/jobs/h17-conditional")
    p.add_argument("--out", default="/root/work/reports/h17/report.md")
    main(p.parse_args())
