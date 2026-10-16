"""自进化闭环：可修改范围（agenteval/loop/scope.py）。"""
from agenteval.loop.scope import AUTO, KNOBS, POLICY, effective_options, fingerprint, policy_options, scope_table, validate_change

# 当前在用的 H2（qroll-h2-synth-train 的 agent kwargs，含训练专用的 store_all_messages）
H2 = {"interface_fixes": True, "completion_gate": True, "raw_log": True, "verifier_gate": "none", "adaptive_wait": False,
      "task_contract": False, "deliverable_checkpoint": False, "store_all_messages": True, "max_turns": 100}


def test_policy_options_fill_defaults_and_drop_everything_outside_auto():
    p = policy_options(H2)
    assert set(p) == set(POLICY) and set(AUTO) < set(POLICY)
    assert p["custom_notes"] == [] and p["skills"] == []
    assert p["interface_fixes"] is True and p["wait_cap_sec"] == 30.0
    assert "raw_log" not in p and "store_all_messages" not in p and "max_turns" not in p


def test_effective_options_drop_params_whose_switch_is_off():
    assert "wait_cap_sec" not in effective_options(H2)
    assert effective_options({**H2, "adaptive_wait": True})["wait_cap_sec"] == 30.0


def test_fingerprint_is_the_same_when_only_an_inactive_param_differs():
    assert fingerprint(H2) == fingerprint({**H2, "wait_cap_sec": 99.0})
    assert fingerprint(H2) != fingerprint({**H2, "adaptive_wait": True})


def test_frozen_training_only_and_unknown_options_are_refused():
    for change, fragment in [({"raw_log": False}, "frozen"), ({"teacher_hint": True}, "training-only"),
                             ({"max_turns": 50}, "frozen"), ({"hint_every": 3}, "training-only"),
                             ({"new_reminder_prompt": "check your work"}, "unknown option")]:
        v = validate_change(H2, change)
        assert not v.ok and any(fragment in e for e in v.errors), (change, v.errors)


def test_type_range_enum_and_dependency_checks():
    assert not validate_change(H2, {"adaptive_wait": "yes"}).ok
    assert not validate_change(H2, {"adaptive_wait": True, "wait_cap_sec": True}).ok          # bool 不算数字
    v = validate_change(H2, {"adaptive_wait": True, "wait_cap_sec": 500})
    assert not v.ok and "out of range" in v.errors[0]
    v = validate_change(H2, {"wait_cap_sec": 60})
    assert not v.ok and "requires adaptive_wait" in v.errors[0]
    assert not validate_change(H2, {"verifier_gate": "auditor"}).ok
    assert not validate_change(H2, {"task_contract": True, "contract_version": 3}).ok
    v = validate_change(H2, {"task_contract": True, "contract_version": 2, "contract_conditional": True})
    assert not v.ok and any("contract_version=1" in e for e in v.errors)


def test_valid_change_reports_the_effective_difference():
    v = validate_change(H2, {"adaptive_wait": True, "wait_cap_sec": 60})
    assert v.ok, v.errors
    assert v.effective_changes == {"adaptive_wait": True, "wait_stable_sec": 3.0, "wait_cap_sec": 60.0}
    assert v.options["wait_cap_sec"] == 60.0 and isinstance(v.options["wait_cap_sec"], float)


def test_a_change_that_leaves_the_same_harness_is_refused():
    v = validate_change(H2, {"interface_fixes": True})
    assert not v.ok and "no effective change" in v.errors[0]
    assert not validate_change(H2, {}).ok


def test_scope_table_lists_every_knob():
    rows = scope_table()
    assert {r["option"] for r in rows} == set(KNOBS)
    assert next(r for r in rows if r["option"] == "wait_cap_sec")["allowed"] == [10.0, 120.0]


def test_review_tier_mechanism_needs_human_approval():
    from agenteval.loop import scope
    scope.KNOBS["_new_mech"] = scope.Knob("_new_mech", "bool", "review", False)
    try:
        v = validate_change(H2, {"_new_mech": True})
        assert not v.ok and "human approval" in v.errors[0]
    finally:
        del scope.KNOBS["_new_mech"]
    assert validate_change(H2, {"append_nudge": True}).ok                 # 2026-10-13 批准后是 auto


def test_fingerprint_ignores_options_left_at_their_default():
    assert fingerprint(H2) == fingerprint({**H2, "adaptive_wait": False, "verifier_gate": "none"})
    assert fingerprint({}) != fingerprint(H2)


def test_dependencies_are_followed_all_the_way_up():
    # gate_timeout_sec 依赖 contract_conditional，后者依赖 task_contract：task_contract 关着时它不起作用
    a = {**H2, "task_contract": False, "contract_conditional": True, "gate_timeout_sec": 120.0}
    assert "gate_timeout_sec" not in effective_options(a) and fingerprint(a) == fingerprint(H2)


def test_int_and_float_spellings_are_the_same_harness():
    a = {**H2, "adaptive_wait": True, "wait_cap_sec": 60}
    b = {**H2, "adaptive_wait": True, "wait_cap_sec": 60.0}
    assert fingerprint(a) == fingerprint(b)


def test_nan_and_infinity_are_refused():
    for bad in (float("nan"), float("inf")):
        v = validate_change(H2, {"adaptive_wait": True, "wait_cap_sec": bad})
        assert not v.ok and "finite" in v.errors[0]



# ---- text 档（D-089）：提醒和 skill 只查格式；文字内容由 notes.screen_note 和人把关
NOTE = {"trigger": "repeat_command", "text": "You sent the same command {n} times in a row; change something first."}
SKILL = {"name": "write-whole-files", "description": "Write a file in one command", "body": "Use a heredoc: cat > f << 'EOF' ... EOF."}


def test_text_knobs_do_not_change_existing_fingerprints():
    assert fingerprint(H2) == fingerprint({**H2, "custom_notes": [], "skills": []})


def test_valid_note_and_skill_are_accepted_and_change_the_fingerprint():
    v = validate_change(H2, {"custom_notes": [NOTE]})
    assert v.ok and v.effective_changes["custom_notes"][0]["trigger"] == "repeat_command"
    assert fingerprint(v.options) != fingerprint(H2)
    w = validate_change(H2, {"skills": [SKILL]})
    assert w.ok and fingerprint(w.options) not in (fingerprint(H2), fingerprint(v.options))


def test_note_format_rules():
    bad = [
        {"custom_notes": [{"trigger": "made_up", "text": "x"}]},                                   # 不在菜单里
        {"custom_notes": [{"trigger": "repeat_command", "text": "word " * 61}]},                  # 太长
        {"custom_notes": [{"trigger": "repeat_command", "text": "see {task} now"}]},              # 不认识的占位符
        {"custom_notes": [{"trigger": "repeat_command", "text": "stop editing {files}"}]},        # {files} 只给 append_streak
        {"custom_notes": [NOTE, dict(NOTE, text="again")]},                                        # 同一个触发条件两条
        {"custom_notes": [NOTE, {"trigger": "same_error", "text": "a"}, {"trigger": "turn_budget", "text": "b"}]},   # 超过 2 条
        {"custom_notes": [{"trigger": "repeat_command", "text": "x", "extra": 1}]},                # 多余字段
    ]
    for c in bad:
        assert not validate_change(H2, c).ok, c


def test_skill_format_rules():
    bad = [dict(SKILL, name="Bad Name"), dict(SKILL, description="w " * 31), dict(SKILL, body="w " * 301), dict(SKILL, body=" ")]
    for sk in bad:
        assert not validate_change(H2, {"skills": [sk]}).ok, sk
    assert not validate_change(H2, {"skills": [SKILL, SKILL]}).ok                                  # 重名


def test_scope_table_lists_the_trigger_menu_for_the_proposer():
    row = next(r for r in scope_table() if r["option"] == "custom_notes")
    assert row["tier"] == "text" and "repeat_command" in row["allowed"]["triggers"]
