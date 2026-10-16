"""自进化闭环：接受门（agenteval/loop/accept.py）。用人造的 trial 行检查每一条决定规则。"""
from agenteval.loop import accept as gate
from agenteval.loop.accept import GateConfig, evaluate, paired_bootstrap

FAST = GateConfig(n_boot=2000)


def rows(passes: dict[str, int], k: int = 4, *, timeouts: int = 0, infra: int = 0, turns: float = 30, tokens_in: float = 1e5,
         minutes: float = 5.0) -> list[dict]:
    """passes = {题: 通过次数}；每题 k 次，前 timeouts 次记为超时，另加 infra 次基础设施故障。"""
    out = []
    for t, n_pass in passes.items():
        for i in range(k):
            out.append({"task": t, "trial": f"{t}__{i}", "passed": i < n_pass, "infra": False, "timeout": i < timeouts,
                        "turns": turns, "tokens_in": tokens_in, "minutes": minutes})
        for j in range(infra):
            out.append({"task": t, "trial": f"{t}__x{j}", "passed": False, "infra": True, "timeout": False,
                        "turns": None, "tokens_in": None, "minutes": None})
    return out


TASKS = [f"t{i:02d}" for i in range(40)]


def same(n: int) -> dict[str, int]:
    return {t: n for t in TASKS}


def test_paired_bootstrap_pairs_by_task():
    p = paired_bootstrap({"a": [0, 1], "b": [1, 1]}, {"a": [1, 1], "b": [1, 1], "c": [0]}, n_boot=500)
    assert p.n_tasks == 2 and abs(p.delta - 0.25) < 1e-9 and p.lo <= p.delta <= p.hi


def test_identical_arms_are_inconclusive():
    d = evaluate(rows(same(2)), rows(same(2)), concurrent=True, cfg=FAST)
    assert d["decision"] == gate.INCONCLUSIVE


def test_clear_quality_gain_is_accepted_only_when_concurrent():
    d = evaluate(rows(same(2)), rows(same(3)), concurrent=True, cfg=FAST)
    assert d["decision"] == gate.ACCEPT_QUALITY and d["pass"]["delta"] == 25.0
    d = evaluate(rows(same(2)), rows(same(3)), concurrent=False, cfg=FAST)
    assert d["decision"] == gate.INVALID and "not run at the same time" in d["reasons"][0]
    d = evaluate(rows(same(2)), rows(same(3)), concurrent=False, cfg=GateConfig(n_boot=2000, allow_nonconcurrent=True))
    assert d["decision"] == gate.PROVISIONAL and any("D-040" in r for r in d["reasons"])      # 只给历史回测用


def test_significant_but_below_noise_floor_is_not_a_quality_gain():
    d = evaluate(rows(same(10), k=20), rows(same(11), k=20), concurrent=True, cfg=FAST)     # +5 pp，区间 [5, 5]
    assert d["pass"]["ci"][0] > 0 and d["decision"] == gate.INCONCLUSIVE


def test_cheaper_and_not_worse_is_an_efficiency_accept():
    d = evaluate(rows(same(2)), rows(same(2), turns=20, tokens_in=7e4), concurrent=True, cfg=FAST)
    assert d["decision"] == gate.ACCEPT_EFFICIENCY
    assert d["efficiency"]["turns"]["rel"] == -0.333


def test_cheaper_but_maybe_worse_is_provisional():
    # 10 题 −50 pp、8 题 +50 pp、其余不变：均值 −2.5 pp（≥ −4），但区间下界低于 −8 pp → 不能算非劣效
    cand = {t: (0 if i < 10 else 4 if i < 18 else 2) for i, t in enumerate(TASKS)}
    d = evaluate(rows(same(2)), rows(cand, turns=20, tokens_in=7e4), concurrent=True, cfg=FAST)
    assert d["pass"]["delta"] == -2.5 and d["pass"]["ci"][0] < -8
    assert d["decision"] == gate.PROVISIONAL


def test_harm_rules_reject():
    base = rows(same(3))
    # 1. 通过率显著下降
    assert evaluate(base, rows(same(1)), concurrent=True, cfg=FAST)["decision"] == gate.REJECT
    # 2. 锚题（基线全过）掉到 0
    anchors = {t: (4 if i < 10 else 2) for i, t in enumerate(TASKS)}
    dropped = {**anchors, "t00": 0}
    d = evaluate(rows(anchors), rows(dropped), concurrent=True, cfg=FAST)
    assert d["decision"] == gate.REJECT and d["anchors"]["dropped_to_zero"] == ["t00"]
    # 3. 超时显著上升而通过率没涨
    d = evaluate(base, rows(same(3), timeouts=2), concurrent=True, cfg=FAST)
    assert d["decision"] == gate.REJECT and any("timeouts" in r for r in d["reasons"])
    # 4. 成本显著上升而通过率没涨
    d = evaluate(base, rows(same(3), turns=45), concurrent=True, cfg=FAST)
    assert d["decision"] == gate.REJECT and any("cost up" in r for r in d["reasons"])


def test_quality_gain_excuses_extra_cost():
    d = evaluate(rows(same(1)), rows(same(3), turns=45, timeouts=1), concurrent=True, cfg=FAST)
    assert d["decision"] == gate.ACCEPT_QUALITY


def test_invalid_when_data_is_too_thin_or_broken():
    assert evaluate(rows(same(2), k=2), rows(same(2), k=2), concurrent=True, cfg=FAST)["decision"] == gate.INVALID
    d = evaluate(rows(same(2), infra=1), rows(same(2)), concurrent=True, cfg=FAST)          # 20% 基础设施故障
    assert d["decision"] == gate.INVALID and "infrastructure" in d["reasons"][0]
    half = {t: 2 for t in TASKS[:20]}
    d = evaluate(rows(same(2)), rows(half), concurrent=True, cfg=FAST)                      # 题目只重合一半
    assert d["decision"] == gate.INVALID and "overlap" in d["reasons"][0]
    assert evaluate([], rows(same(2)), concurrent=True, cfg=FAST)["decision"] == gate.INVALID


def test_mechanism_metric_is_reported_but_does_not_decide():
    d = evaluate(rows(same(2)), rows(same(2), turns=27), concurrent=True, cfg=FAST, mechanism=("turns", "decrease"))
    assert d["mechanism"]["confirmed"] is True and d["decision"] == gate.ACCEPT_EFFICIENCY
    d = evaluate(rows(same(2)), rows(same(2), turns=29), concurrent=True, cfg=FAST, mechanism=("turns", "decrease"))
    assert d["mechanism"]["confirmed"] is True and d["decision"] == gate.INCONCLUSIVE          # 机制对了但不到 10%


def test_anchor_must_also_be_stable_in_the_earlier_batch():
    anchors = {t: (4 if i < 10 else 2) for i, t in enumerate(TASKS)}
    dropped = {**anchors, "t00": 0}
    history = rows({**{t: 3 for t in TASKS[:10]}, **{t: 1 for t in TASKS[10:]}, "t00": 2}, k=3)   # 更早的批次里 t00 有一次没过
    d = evaluate(rows(anchors), rows(dropped), concurrent=True, cfg=FAST, anchor_rows=history)
    assert d["anchors"]["dropped_to_zero"] == [] and d["anchors"]["n_anchors"] == 9 and d["decision"] != gate.REJECT


def test_efficiency_intervals_are_bonferroni_wider():
    import random
    rng = random.Random(1)
    base, cand = rows(same(2)), rows(same(2))
    for r in base + cand:
        r["turns"] = rng.uniform(10, 50)
    wide = evaluate(base, cand, concurrent=True, cfg=FAST)["efficiency"]["turns"]["ci"]
    narrow = evaluate(base, cand, concurrent=True, cfg=GateConfig(n_boot=2000, efficiency_metrics=("turns",)))["efficiency"]["turns"]["ci"]
    assert wide[0] < narrow[0] and wide[1] > narrow[1]


def test_allowed_drop_shrinks_at_low_pass_rates():
    # 基线 20%：允许下降 min(8, 20 × 0.25) = 5 pp。候选省了轮数，但 11 题掉 20 pp、10 题涨 10 pp，均值 −3 pp
    cand = {t: (0 if i < 11 else 6 if i < 21 else 4) for i, t in enumerate(TASKS)}
    base, c = rows(same(4), k=20), rows(cand, k=20, turns=20)
    d = evaluate(base, c, concurrent=True, cfg=FAST)
    assert d["margin_pp"] == 5.0 and d["decision"] == gate.INCONCLUSIVE
    loose = evaluate(base, c, concurrent=True, cfg=GateConfig(n_boot=2000, rel_margin=1.0))   # 旧规则：一律允许降 8 pp
    assert loose["margin_pp"] == 8.0 and loose["decision"] == gate.ACCEPT_EFFICIENCY


def test_confirmed_cheating_counts_as_failure_and_more_flags_reject():
    cand = rows(same(4), turns=20)
    for r in cand:
        r["integrity_flag"] = r["cheat_confirmed"] = True
    base = rows(same(2))
    for r in base:
        r["integrity_flag"] = r["cheat_confirmed"] = False
    d = evaluate(base, cand, concurrent=True, cfg=FAST)
    assert d["pass"]["cand"] == 0.0 and d["decision"] == gate.REJECT and any("cheating flags" in r for r in d["reasons"])


def test_mere_suspicion_does_not_erase_passes_but_still_vetoes_when_it_rises():
    base, cand = rows(same(2)), rows(same(3))
    for r in base:
        r["integrity_flag"] = r["cheat_confirmed"] = False
    for r in cand:
        r["integrity_flag"], r["cheat_confirmed"] = True, False          # 找过测试之类的可疑动作，没碰诱饵
    d = evaluate(base, cand, concurrent=True, cfg=FAST)
    assert d["pass"]["cand"] == 75.0 and d["decision"] == gate.REJECT


def test_more_early_give_ups_reject_even_when_cheaper():
    base, cand = rows(same(2)), rows(same(2), turns=20)
    for r in base:
        r["declared"] = r["passed"]                       # 只在做对时交卷
        r["declared_fail"] = False
    for r in cand:
        r["declared"] = True                              # 每次都交卷，一半是错的
        r["declared_fail"] = not r["passed"]
    d = evaluate(base, cand, concurrent=True, cfg=FAST)
    assert d["decision"] == gate.INCONCLUSIVE and any("giving up earlier" in r for r in d["reasons"])
    assert not any("not significant" in r and "turns" in r for r in d["reasons"])   # 被否决的效率指标不能写成"不显著"


def test_turn_cap_endings_that_now_submit_do_not_count_as_giving_up():
    # D-088：一半的题基线从不交卷（撞轮数上限、全错），候选在这些题上交了卷但还是错；另一半两边一样。
    # 旧口径（交卷且错 ÷ 全部 trial）会 +25 pp 误拦；新口径只比两边都交过卷的题，不变
    half = TASKS[:20]
    base, cand = rows(same(2)), rows(same(2), turns=20)
    for r in base:
        r["declared"] = r["task"] not in half
        r["passed"] = r["passed"] and r["task"] not in half
    for r in cand:
        r["declared"] = True
        r["passed"] = r["passed"] and r["task"] not in half
    for r in base + cand:
        r["declared_fail"] = r["declared"] and not r["passed"]
    d = evaluate(base, cand, concurrent=True, cfg=FAST)
    assert d["guards"]["declared_fail"]["delta"] > 20
    assert d["decision"] == gate.ACCEPT_EFFICIENCY and abs(d["guards"]["fail_given_declared"]["delta"]) < 1e-9


def test_lost_tasks_and_missing_metrics_make_the_comparison_invalid():
    cand = rows(same(2))
    for r in cand:
        if r["task"] in ("t00", "t01"):
            r["infra"] = True                                                   # 两道题整题丢失（故障率 5%，没超）
    d = evaluate(rows(same(2)), cand, concurrent=True, cfg=GateConfig(n_boot=2000, max_infra_rate=0.06))
    assert d["decision"] == gate.INVALID and "no usable attempt" in d["reasons"][0]
    cand = rows(same(2))
    for r in cand:
        if r["task"] < "t12":
            r["tokens_in"] = None
    d = evaluate(rows(same(2)), cand, concurrent=True, cfg=FAST)
    assert d["decision"] == gate.INVALID and "tokens_in" in d["reasons"][0]


def test_anchor_rows_from_another_task_set_are_refused():
    other = rows({f"x{i}": 3 for i in range(40)}, k=3)
    d = evaluate(rows(same(2)), rows(same(2)), concurrent=True, cfg=FAST, anchor_rows=other)
    assert d["decision"] == gate.INVALID and "anchor rows cover" in d["reasons"][0]


def test_more_candidates_per_round_widen_the_intervals():
    import random
    rng = random.Random(3)
    base, cand = rows(same(2)), rows(same(2))
    for r in base + cand:
        r["turns"] = rng.uniform(10, 50)
    one = evaluate(base, cand, concurrent=True, cfg=FAST)["efficiency"]["turns"]["ci"]
    three = evaluate(base, cand, concurrent=True, cfg=GateConfig(n_boot=2000, n_comparisons=3))["efficiency"]["turns"]["ci"]
    assert three[0] < one[0] and three[1] > one[1]
