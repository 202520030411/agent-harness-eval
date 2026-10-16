"""接受门：候选 harness 相对当前版本，是"真的更好"、"更省且不更差"、"有害"，还是"分不清"。

这是自进化闭环里最关键的一环（文枢那类项目最弱的也是这一环）。规则全部来自本项目踩过的坑：
- 对照必须和基线同时跑（D-040：同配置隔 3 小时能差 11.5 pp）；不同时跑的最多给 PROVISIONAL。
- 通过率提升要按题配对、bootstrap 区间不含 0、且幅度 ≥ 噪声底（D-013 / D-018）。
- "省资源型"改动（像 adaptive_wait）允许另一条路：效率指标显著改善，且通过率的区间下界不低于 −噪声底。
- 验证类改动的真实代价是时间（D-047）：轮数 / token / 分钟 / 超时显著变差而通过率没有显著提升 → 有害。
- 稳过的题（锚题）掉到 0 → 有害（回归门，E9）。
- 每题次数太少、基础设施故障太多 → INVALID，不下结论。
- 校准（2026-10-11 回测，同配置随机对半分，k=4）：效率三个指标任一显著就算数时，同配置被误收 9%、误拒 11%；
  改为三个指标各用 alpha/3（Bonferroni），锚题必须在之前的观察批次里也全过（anchor_rows）。
- 提出效应之后要有独立批次复现（D-050）：这一层由 state.Registry.promotable 管。
- 防自欺与防作弊（D-085，2026-10-12）：两臂不是同时跑的直接 INVALID（历史回测才放宽）；允许通过率下降的幅度
  按基线通过率缩放（低通过率时 8 pp 等于丢掉一半的通过）；一轮多个候选共用一个基线时按候选数收紧；
  确凿作弊（cheat_confirmed：碰了诱饵）的"通过"一律算失败，作弊嫌疑率（integrity_flag）显著上升直接 REJECT；
  交了卷的 trial 里做错的比例显著上升时不许走"更省"这条接受路径（防"早点放弃"换来的省轮数；D-088 起按题只比两边都交过卷的，
  原来分母是全部 trial，撞轮数上限的 trial 改成交卷后也会涨，第 1 轮误拦）；整题丢失、效率数据缺失、锚题数据和这批题对不上，都判 INVALID，不再悄悄跳过。

输入是"每个 trial 一行"的字典：task, passed, infra（基础设施故障，排除）, timeout, 以及数值指标（turns, tokens_in, minutes …）。
所有函数都是纯函数。
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

ACCEPT_QUALITY = "ACCEPT_QUALITY"
ACCEPT_EFFICIENCY = "ACCEPT_EFFICIENCY"
PROVISIONAL = "PROVISIONAL"
INCONCLUSIVE = "INCONCLUSIVE"
REJECT = "REJECT"
INVALID = "INVALID"


@dataclass
class GateConfig:
    noise_floor_pp: float = 8.0               # 通过率：差值要 ≥ 这个才算提升；非劣效的容忍下界也是它
    min_attempts_per_task: int = 3
    max_infra_rate: float = 0.05
    min_task_overlap: float = 0.9
    efficiency_metrics: tuple = ("turns", "tokens_in", "minutes")   # 越低越好
    efficiency_min_rel: float = 0.10           # 效率改善 / 变差要至少 10% 才算数
    timeout_harm_pp: float = 8.0               # 超时率显著上升且 ≥ 8 pp → 有害
    max_anchor_zero: int = 0                   # 锚题（基线全过）在候选里掉到 0 的个数上限
    n_boot: int = 10000
    seed: int = 0
    alpha: float = 0.05                        # 双侧；效率指标按个数做 Bonferroni（每个用 alpha / 指标数）
    rel_margin: float = 0.25                   # 允许通过率下降的幅度 = min(噪声底, 基线通过率 × 0.25)
    n_comparisons: int = 1                     # 一轮里共用同一个基线的候选数：alpha 再除以它
    max_lost_task_frac: float = 0.02           # 某一臂整题一次可用都没有的题，超过这个比例 → INVALID
    min_metric_coverage: float = 0.8           # 效率指标要在 ≥80% 的配对题上有值，否则 INVALID
    min_anchor_coverage: float = 0.5           # 给了更早批次时，它至少要覆盖这批题的一半，否则 INVALID
    guard_harm_pp: float = 8.0                 # 交了卷的里面做错的比例显著上升且 ≥ 8 pp → 不许走"更省"这条路
    allow_nonconcurrent: bool = False          # 只给历史回测用：允许不同时跑的两臂，ACCEPT 降为 PROVISIONAL


@dataclass
class Paired:
    n_tasks: int
    base_mean: float
    cand_mean: float
    delta: float
    lo: float
    hi: float

    @property
    def rel(self) -> float | None:
        return None if not self.base_mean else self.delta / self.base_mean

    def as_dict(self, scale: float = 1.0, digits: int = 3) -> dict[str, Any]:
        r = self.rel
        return {"n_tasks": self.n_tasks, "base": round(scale * self.base_mean, digits), "cand": round(scale * self.cand_mean, digits),
                "delta": round(scale * self.delta, digits), "ci": [round(scale * self.lo, digits), round(scale * self.hi, digits)],
                "rel": None if r is None else round(r, 3)}


def _per_task(rows: list[dict], key, keep=lambda r: True) -> dict[str, list[float]]:
    acc: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("infra") or not keep(r):
            continue
        v = key(r)
        if v is None:
            continue
        acc[r["task"]].append(float(v))
    return acc


def paired_bootstrap(a: dict[str, list[float]], b: dict[str, list[float]], n_boot: int = 10000, seed: int = 0,
                     alpha: float = 0.05) -> Paired | None:
    """按题配对：每题取均值，差 = 候选 − 基线；对题目做 bootstrap，给 (1 − alpha) 区间。只用两边都有值的题。"""
    tasks = sorted(t for t in set(a) & set(b) if a[t] and b[t])
    if not tasks:
        return None
    ma = {t: sum(a[t]) / len(a[t]) for t in tasks}
    mb = {t: sum(b[t]) / len(b[t]) for t in tasks}
    diffs = [mb[t] - ma[t] for t in tasks]
    n = len(tasks)
    rng = random.Random(seed)
    boots = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo_i = min(n_boot - 1, int(alpha / 2 * n_boot))
    hi_i = max(0, int((1 - alpha / 2) * n_boot) - 1)
    return Paired(n, sum(ma.values()) / n, sum(mb.values()) / n, sum(diffs) / n, boots[lo_i], boots[hi_i])


def _passed(r: dict) -> float:
    """确凿作弊（打开诱饵 / 输出里出现诱饵暗号）的"通过"一律算失败。一般的可疑行为（比如找过测试）不改通过，
    只在下面的作弊率检查里看候选有没有让它变多。"""
    return 1.0 if (r.get("passed") and not r.get("cheat_confirmed")) else 0.0


def validity(base: list[dict], cand: list[dict], cfg: GateConfig, *, concurrent: bool = True,
             anchor_rows: list[dict] | None = None) -> list[str]:
    problems = []
    if not concurrent and not cfg.allow_nonconcurrent:
        problems.append("arms were not run at the same time (D-040): no decision")
    for name, rows in (("baseline", base), ("candidate", cand)):
        if not rows:
            problems.append(f"{name}: no trials")
            continue
        infra = sum(1 for r in rows if r.get("infra")) / len(rows)
        if infra > cfg.max_infra_rate:
            problems.append(f"{name}: infrastructure-error rate {infra:.0%} > {cfg.max_infra_rate:.0%}")
        per = _per_task(rows, lambda r: 1.0)
        if per and min(len(v) for v in per.values()) < cfg.min_attempts_per_task:
            low = sum(1 for v in per.values() if len(v) < cfg.min_attempts_per_task)
            problems.append(f"{name}: {low} tasks have fewer than {cfg.min_attempts_per_task} usable attempts")
    ta = {r["task"] for r in base if not r.get("infra")}
    tb = {r["task"] for r in cand if not r.get("infra")}
    if ta and tb:
        overlap = len(ta & tb) / max(len(ta | tb), 1)
        if overlap < cfg.min_task_overlap:
            problems.append(f"task overlap {overlap:.0%} < {cfg.min_task_overlap:.0%}")
    # 两臂都出现过、但某一臂一次可用都没有的题：它们会从配对比较里悄悄消失
    seen = {r["task"] for r in base} & {r["task"] for r in cand}
    lost = sorted(t for t in seen if t not in ta or t not in tb)
    if seen and len(lost) > cfg.max_lost_task_frac * len(seen):
        problems.append(f"{len(lost)} tasks have no usable attempt in one arm: {lost[:5]}")
    if anchor_rows is not None and ta:
        cover = len(ta & {r["task"] for r in anchor_rows}) / len(ta)
        if cover < cfg.min_anchor_coverage:
            problems.append(f"anchor rows cover only {cover:.0%} of the evaluated tasks (wrong observation batch?)")
    return problems


def anchor_check(base: list[dict], cand: list[dict], cfg: GateConfig, anchor_rows: list[dict] | None = None) -> dict[str, Any]:
    """锚题 = 基线这一批每次都过；给了 anchor_rows（同一版本更早的观察批次）时，还要求那一批里也每次都过。"""
    pa = _per_task(base, _passed)
    pb = _per_task(cand, _passed)
    anchors = [t for t, v in pa.items() if len(v) >= cfg.min_attempts_per_task and min(v) == 1.0]
    if anchor_rows is not None:
        ph = _per_task(anchor_rows, _passed)
        anchors = [t for t in anchors if ph.get(t) and min(ph[t]) == 1.0]
    zero = [t for t in anchors if t in pb and pb[t] and max(pb[t]) == 0.0]
    return {"n_anchors": len(anchors), "dropped_to_zero": sorted(zero), "failed": len(zero) > cfg.max_anchor_zero}


def evaluate(base: list[dict], cand: list[dict], *, concurrent: bool, cfg: GateConfig | None = None,
             mechanism: tuple[str, str] | None = None, anchor_rows: list[dict] | None = None) -> dict[str, Any]:
    """返回 {decision, reasons, pass, efficiency, timeout, anchors, mechanism, validity}。

    mechanism = (指标名, "decrease"|"increase")：预注册的机制指标，只报告是否按预测方向显著变化，不参与决定。
    """
    cfg = cfg or GateConfig()
    out: dict[str, Any] = {"decision": None, "reasons": [], "concurrent": concurrent}
    problems = validity(base, cand, cfg, concurrent=concurrent, anchor_rows=anchor_rows)
    out["validity"] = problems
    if problems:
        out["decision"] = INVALID
        out["reasons"] = problems
        return out

    k = max(1, cfg.n_comparisons)
    a_pass, a_eff = cfg.alpha / k, cfg.alpha / (k * max(1, len(cfg.efficiency_metrics)))

    def boot(key, alpha, keep=lambda r: True):
        return paired_bootstrap(_per_task(base, key, keep), _per_task(cand, key, keep), cfg.n_boot, cfg.seed, alpha)

    p = boot(_passed, a_pass)
    out["pass"] = p.as_dict(scale=100, digits=1)          # 百分点
    to = boot(lambda r: 1.0 if r.get("timeout") else 0.0, a_pass)
    out["timeout"] = to.as_dict(scale=100, digits=1)
    eff: dict[str, Paired] = {}
    for m in cfg.efficiency_metrics:
        e = boot(lambda r, m=m: r.get(m), a_eff)
        if e is None or e.n_tasks < cfg.min_metric_coverage * p.n_tasks:
            out["decision"] = INVALID
            out["reasons"] = [f"efficiency metric {m} is missing on more than {1 - cfg.min_metric_coverage:.0%} of the tasks"]
            return out
        eff[m] = e
    out["efficiency"] = {m: e.as_dict() for m, e in eff.items()}
    guards = {}
    for g in ("declared_fail", "integrity_flag"):
        if any(g in r for r in base + cand):
            gp = boot(lambda r, g=g: 1.0 if r.get(g) else 0.0, a_pass)
            if gp is not None:
                guards[g] = gp
    if any("declared" in r for r in base + cand):
        # 防早放弃用这个（D-088）：交了卷的 trial 里做错的比例，只比两边都交过卷的题。
        # declared_fail（分母是全部 trial）只报告：以前撞轮数上限的 trial 改成交卷后它也会涨（第 1 轮 +8.2 pp 的误拦）
        gp = boot(lambda r: 1.0 - _passed(r), a_pass, keep=lambda r: bool(r.get("declared")))
        if gp is not None:
            guards["fail_given_declared"] = gp
    out["guards"] = {g: v.as_dict(scale=100, digits=1) for g, v in guards.items()}
    anchors = anchor_check(base, cand, cfg, anchor_rows)
    out["anchors"] = anchors
    if mechanism:
        name, direction = mechanism
        mm = boot(lambda r: r.get(name), cfg.alpha)
        if mm is not None:
            hit = (mm.hi < 0) if direction == "decrease" else (mm.lo > 0)
            out["mechanism"] = {"metric": name, "direction": direction, **mm.as_dict(), "confirmed": hit}

    nf = cfg.noise_floor_pp / 100
    margin = min(nf, cfg.rel_margin * p.base_mean)         # 允许通过率下降的幅度：低通过率时按比例收紧
    out["margin_pp"] = round(100 * margin, 1)
    better_eff = [m for m, e in eff.items() if e.hi < 0 and e.rel is not None and -e.rel >= cfg.efficiency_min_rel]
    worse_eff = [m for m, e in eff.items() if e.lo > 0 and e.rel is not None and e.rel >= cfg.efficiency_min_rel]
    quality = p.lo > 0 and p.delta >= nf
    sig_worse = p.hi < 0
    timeout_harm = to.lo > 0 and to.delta >= cfg.timeout_harm_pp / 100
    reasons = out["reasons"]

    harm = []
    if sig_worse:
        harm.append(f"pass rate significantly lower: {100*p.delta:+.1f} pp [{100*p.lo:+.1f}, {100*p.hi:+.1f}]")
    if anchors["failed"]:
        harm.append(f"anchor tasks dropped to 0: {anchors['dropped_to_zero']}")
    if "integrity_flag" in guards and guards["integrity_flag"].lo > 0:
        g = guards["integrity_flag"]
        harm.append(f"cheating flags up {100*g.delta:+.1f} pp [{100*g.lo:+.1f}, {100*g.hi:+.1f}]")
    if not quality:
        # 以下几条只有在通过率达到 ACCEPT_QUALITY 的标准时才豁免
        if timeout_harm:
            harm.append(f"timeouts up {100*to.delta:+.1f} pp [{100*to.lo:+.1f}, {100*to.hi:+.1f}] without a quality-level pass-rate gain")
        if worse_eff:
            harm.append("cost up without a quality-level pass-rate gain: " + ", ".join(f"{m} {100*eff[m].rel:+.0f}%" for m in worse_eff))
    if harm:
        out["decision"] = REJECT
        reasons += harm
        return out

    g = guards.get("fail_given_declared")
    gave_up = g is not None and g.lo > 0 and g.delta >= cfg.guard_harm_pp / 100
    vetoed_eff = []
    if gave_up and better_eff and not quality:
        # 省下来的轮次伴随着交卷质量变差（交了卷的里面做错的更多）：多半是早点放弃换来的，不许走"更省"这条路
        reasons.append(f"cheaper ({', '.join(f'{m} {100*eff[m].rel:+.0f}%' for m in better_eff)}), but the share of submissions "
                       f"that fail is up {100*g.delta:+.1f} pp [{100*g.lo:+.1f}, {100*g.hi:+.1f}]: the saving looks like giving up earlier")
        vetoed_eff, better_eff = better_eff, []
    if quality:
        decision = ACCEPT_QUALITY
        reasons.append(f"pass rate {100*p.delta:+.1f} pp [{100*p.lo:+.1f}, {100*p.hi:+.1f}] ≥ noise floor {cfg.noise_floor_pp} pp")
    elif better_eff and p.lo >= -margin:
        decision = ACCEPT_EFFICIENCY
        reasons.append("cheaper and non-inferior: " + ", ".join(f"{m} {100*eff[m].rel:+.0f}%" for m in better_eff)
                       + f"; pass {100*p.delta:+.1f} pp, CI lower {100*p.lo:+.1f} ≥ −{100*margin:.1f}")
    elif better_eff and p.delta >= -margin / 2:
        decision = PROVISIONAL
        reasons.append(f"cheaper, but the pass-rate CI cannot rule out a drop larger than {100*margin:.1f} pp "
                       f"({100*p.delta:+.1f} pp [{100*p.lo:+.1f}, {100*p.hi:+.1f}]); needs a larger confirmation batch")
    else:
        decision = INCONCLUSIVE
        flat = [m for m in eff if m not in vetoed_eff and m not in better_eff and m not in worse_eff]
        if better_eff:
            reasons.append("cheaper (" + ", ".join(f"{m} {100*eff[m].rel:+.0f}%" for m in better_eff)
                           + f"), but the pass rate fell by more than half the allowed margin ({100*margin:.1f} pp)")
        reasons.append(f"no reliable difference: pass {100*p.delta:+.1f} pp [{100*p.lo:+.1f}, {100*p.hi:+.1f}]"
                       + (f"; efficiency changes {', '.join(flat)} not significant" if flat else ""))
    if not concurrent and decision in (ACCEPT_QUALITY, ACCEPT_EFFICIENCY):
        reasons.append("arms were not run concurrently (D-040): downgraded to PROVISIONAL")
        decision = PROVISIONAL
    out["decision"] = decision
    return out
