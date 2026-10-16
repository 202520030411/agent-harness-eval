"""自进化闭环：失败模式表（agenteval/loop/modes.py）与反思分队列（agenteval/loop/reflect.py）。"""
from agenteval.loop.modes import MODE_BY_ID, MODES, mode_table, summary
from agenteval.loop.reflect import reflect


def r(task: str, i: int, passed: bool, **kw) -> dict:
    row = {"task": task, "trial": f"{task}__{i}", "passed": passed, "infra": False, "timeout": False, "turns": 20, "max_turns": 100,
           "n_parse_err": 0, "json_loop_end": False, "rule_labels": [], "polling_turns": 0, "cnf": False, "echo_theater": False,
           "false_success": False, "no_run_before_claim": False, "minutes": 3.0, "tokens_in": 1000}
    row.update(kw)
    return row


def _rows() -> list[dict]:
    rows = []
    # 10 题 × 3 次：t0–t3 全过；t4–t7 一过两挂；t8–t9 全挂
    for t in range(10):
        for i in range(3):
            passed = t < 4 or (t < 8 and i == 0)
            kw = {}
            if not passed:
                kw = {"polling_turns": 4, "false_success": t % 2 == 0, "cnf": True}
                if t >= 8:
                    kw.update(timeout=True, rule_labels=["BUDGET_EXHAUSTED"])
            rows.append(r(f"t{t}", i, passed, **kw))
    rows.append(r("t0", 9, False, infra=True, polling_turns=9))                   # 基础设施故障：不计
    rows.append(r("t1", 9, True, rule_labels=["INTEGRITY_SUSPECT"]))
    return rows


def test_mode_ids_are_unique_and_lookup_works():
    assert len({m.id for m in MODES}) == len(MODES)
    assert MODE_BY_ID["polling"].prior == "HARNESS"


def test_mode_table_counts_with_the_right_denominator():
    t = {m["mode"]: m for m in mode_table(_rows())}
    # 可评 31 个 trial，其中失败 14 个（t4–t7 各 2，t8–t9 各 3）
    assert t["polling"]["denominator"] == 14 and t["polling"]["n"] == 14 and t["polling"]["among"] == "failed"
    assert t["timeout"]["denominator"] == 31 and t["timeout"]["n"] == 6
    assert t["false_success"]["n"] == 2 + 2 + 3                                     # t4、t6、t8
    assert t["integrity_suspect"]["n"] == 1 and t["integrity_suspect"]["share_of_failures"] == 0.0
    assert t["budget_exhausted"]["n_tasks"] == 2 and len(t["polling"]["examples"]) == 3
    s = summary(_rows())
    assert s["n_trials"] == 32 and s["n_infra"] == 1 and s["n_tasks"] == 10 and abs(s["pass_rate"] - 17 / 31) < 1e-9


def test_reflect_routes_modes_to_three_queues():
    history = [{"id": "E4-adaptive-wait", "switches": "adaptive_wait", "model": "seed", "pass_delta_pp": 0.0,
                "manual_verdict": "efficiency only"}]
    out = reflect(mode_table(_rows()), _rows(), history)
    harness = {x["mode"]: x for x in out["harness_targets"]}
    assert {"polling", "timeout", "budget_exhausted"} <= set(harness)
    assert [h["id"] for h in harness["polling"]["tried"]] == ["E4-adaptive-wait"]
    assert {x["mode"] for x in out["model_targets"]} == {"false_success"}
    human = {x["mode"]: x for x in out["human_review"]}
    assert "command_not_found" in human and "integrity_suspect" in human
    assert human["never_solved"]["tasks"] == ["t8", "t9"]
    assert out["task_difficulty"] == {"never_solved": 2, "mixed_outcome": 4, "always_solved": 4, "n_tasks": 10}
    # 排序：占失败比例高的在前
    shares = [x["share_of_failures"] for x in out["harness_targets"]]
    assert shares == sorted(shares, reverse=True)


def test_rare_modes_are_not_queued():
    rows = [r(f"t{t}", i, i == 0) for t in range(10) for i in range(3)]
    rows[1]["polling_turns"] = 5                                                   # 只有 1 次
    out = reflect(mode_table(rows), rows)
    assert out["harness_targets"] == [] and out["model_targets"] == []
