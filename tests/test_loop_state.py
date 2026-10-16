"""自进化闭环：版本记录与上线 / 回滚规则（agenteval/loop/state.py），包括"闭环不能自欺"的几条硬规则（D-085）。"""
import json

import pytest

from agenteval.loop.scope import effective_options
from agenteval.loop.state import Registry

H2 = {"interface_fixes": True, "completion_gate": True, "raw_log": True}
PRE = {"target_mode": "polling", "mechanism_metric": "polling_turns", "predicted_mechanism_change": "down about 30%",
       "predicted_pass_change": "0 to +3 pp", "falsified_if": "polling_turns not lower than the baseline"}


def _reg() -> Registry:
    r = Registry()
    r.init_root("v0", "terminus2_patches.agent:Terminus2Patched", H2, rationale="H2", model="openai/coder30b")
    return r


def _ev(decision: str) -> dict:
    return {"decision": decision, "reasons": []}


def _propose(r: Registry, changes: dict, parent: str = "v0", **kw):
    v, errs = r.propose(parent, changes, rationale="test", prereg=PRE, source="test", **kw)
    assert v is not None, errs
    return v


def _accept(r: Registry, vid: str, tag: str = "") -> None:
    r.record_evaluation(vid, _ev("ACCEPT_EFFICIENCY"), baseline_job=f"b1{tag}", candidate_job=f"c1{tag}")
    r.record_evaluation(vid, _ev("ACCEPT_QUALITY"), baseline_job=f"b2{tag}", candidate_job=f"c2{tag}", purpose="replication")


def test_init_propose_dedup_and_preregistration(tmp_path):
    r = _reg()
    assert r.current == "v0" and r.versions["v0"].status == "promoted" and r.versions["v0"].model == "openai/coder30b"
    with pytest.raises(ValueError):
        r.init_root("v0b", "x", H2, rationale="again")
    v = _propose(r, {"adaptive_wait": True})
    assert v.version == "v0+c01" and v.status == "proposed" and v.change["adaptive_wait"] is True and v.model == "openai/coder30b"
    dup, errs = r.propose("v0", {"adaptive_wait": True, "wait_cap_sec": 30}, rationale="x", prereg=PRE, source="t")
    assert dup is None and "duplicate" in errs[0]
    bad, errs = r.propose("v0", {"verifier_gate": "self_check"}, rationale="x", prereg={**PRE, "falsified_if": ""}, source="t")
    assert bad is None and "pre-registration" in errs[0]
    ok, errs = r.propose("v0", {"verifier_gate": "self_check"}, rationale="x", prereg={**PRE, "predicted_pass_change": 0}, source="t")
    assert ok is not None, errs                                            # 0 是合法的预测
    bad, errs = r.propose("v0", {"teacher_hint": True}, rationale="x", prereg=PRE, source="t")
    assert bad is None and "frozen" in errs[0]
    bad, errs = r.propose("v0", {"deliverable_checkpoint": True}, rationale="x", prereg=PRE, source="t", version="v0")
    assert bad is None and "already exists" in errs[0]
    p = tmp_path / "registry.json"
    r.save(p)
    r2 = Registry.load(p)
    assert r2.current == "v0" and set(r2.versions) == {"v0", "v0+c01", "v0+c02"} and r2.versions["v0+c01"].prereg == PRE


def test_same_change_for_a_different_model_is_not_a_duplicate():
    r = _reg()
    _propose(r, {"adaptive_wait": True})
    other = _propose(r, {"adaptive_wait": True}, model="openai/coderteach")
    assert other.model == "openai/coderteach"


def test_replication_must_use_new_jobs_and_counts_once():
    r = _reg()
    v = _propose(r, {"adaptive_wait": True})
    assert not r.promotable(v.version)[0]
    r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b1", candidate_job="c1")
    ok, why = r.promotable(v.version)
    assert not ok and "replication" in why
    with pytest.raises(ValueError, match="newly run jobs"):               # 拿主评测的数据冒充复现
        r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b1", candidate_job="c1", purpose="replication")
    with pytest.raises(ValueError, match="newly run jobs"):               # 只换一个臂也不行
        r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b1", candidate_job="c9", purpose="replication")
    with pytest.raises(ValueError, match="already has a primary"):        # 主评测不能重评
        r.record_evaluation(v.version, _ev("ACCEPT_QUALITY"), baseline_job="b5", candidate_job="c5")
    r.record_evaluation(v.version, _ev("ACCEPT_QUALITY"), baseline_job="b2", candidate_job="c2", purpose="replication")
    r.promote(v.version)
    assert r.current == v.version and r.lineage() == ["v0", v.version]
    with pytest.raises(ValueError):
        r.record_evaluation(v.version, _ev("REJECT"), baseline_job="x", candidate_job="y")


def test_a_failed_replication_rejects_the_candidate_for_good():
    r = _reg()
    v = _propose(r, {"adaptive_wait": True})
    r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b1", candidate_job="c1")
    r.record_evaluation(v.version, _ev("INCONCLUSIVE"), baseline_job="b2", candidate_job="c2", purpose="replication")
    assert r.versions[v.version].status == "rejected"
    with pytest.raises(ValueError):                                        # 不能再跑一次复现碰运气
        r.record_evaluation(v.version, _ev("ACCEPT_QUALITY"), baseline_job="b3", candidate_job="c3", purpose="replication")
    with pytest.raises(ValueError):
        r.promote(v.version)


def test_only_invalid_results_may_be_rerun_and_only_with_new_jobs():
    r = _reg()
    v = _propose(r, {"adaptive_wait": True})
    r.record_evaluation(v.version, _ev("INVALID"), baseline_job="b1", candidate_job="c1")
    assert r.versions[v.version].status == "proposed"
    with pytest.raises(ValueError, match="newly run jobs"):
        r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b1", candidate_job="c1")
    r.record_evaluation(v.version, _ev("INCONCLUSIVE"), baseline_job="b2", candidate_job="c2")
    assert r.versions[v.version].status == "evaluated" and not r.promotable(v.version)[0]
    with pytest.raises(ValueError, match="already has a primary"):
        r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b3", candidate_job="c3")


def test_retest_after_a_gate_change_is_allowed_once_and_only_for_inconclusive():
    # D-088：主评测 INCONCLUSIVE、判分代码改过、写明决定编号 → 可以用新 job 重测一次；重测结果代替主评测，之后照常复现
    r = _reg()
    v = _propose(r, {"adaptive_wait": True})
    r.record_evaluation(v.version, _ev("INCONCLUSIVE"), baseline_job="b1", candidate_job="c1", extra={"gate_code": "g1"})
    with pytest.raises(ValueError, match="decision record"):
        r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b2", candidate_job="c2", purpose="retest",
                            extra={"gate_code": "g2"})
    with pytest.raises(ValueError, match="gate code changed"):
        r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b2", candidate_job="c2", purpose="retest",
                            extra={"gate_code": "g1", "decision_ref": "D-088"})
    with pytest.raises(ValueError, match="newly run jobs"):
        r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b1", candidate_job="c2", purpose="retest",
                            extra={"gate_code": "g2", "decision_ref": "D-088"})
    r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b2", candidate_job="c2", purpose="retest",
                        extra={"gate_code": "g2", "decision_ref": "D-088"})
    ok, why = r.promotable(v.version)
    assert not ok and "replication" in why                                  # 重测通过也还要复现
    with pytest.raises(ValueError, match="already retested"):
        r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b3", candidate_job="c3", purpose="retest",
                            extra={"gate_code": "g3", "decision_ref": "D-089"})
    r.record_evaluation(v.version, _ev("ACCEPT_QUALITY"), baseline_job="b4", candidate_job="c4", purpose="replication")
    assert r.promotable(v.version)[0]


def test_retest_is_refused_for_accepted_or_rejected_candidates_and_a_rejecting_retest_closes_it():
    r = _reg()
    a = _propose(r, {"adaptive_wait": True})
    r.record_evaluation(a.version, _ev("PROVISIONAL"), baseline_job="b1", candidate_job="c1", extra={"gate_code": "g1"})
    with pytest.raises(ValueError, match="INCONCLUSIVE primary"):
        r.record_evaluation(a.version, _ev("ACCEPT_QUALITY"), baseline_job="b2", candidate_job="c2", purpose="retest",
                            extra={"gate_code": "g2", "decision_ref": "D-088"})
    b = _propose(r, {"verifier_gate": "self_check"})
    r.record_evaluation(b.version, _ev("INCONCLUSIVE"), baseline_job="b3", candidate_job="c3", extra={"gate_code": "g1"})
    r.record_evaluation(b.version, _ev("REJECT"), baseline_job="b4", candidate_job="c4", purpose="retest",
                        extra={"gate_code": "g2", "decision_ref": "D-088"})
    assert r.versions[b.version].status == "rejected"


def test_provisional_needs_an_accepting_replication():
    r = _reg()
    v = _propose(r, {"adaptive_wait": True})
    r.record_evaluation(v.version, _ev("PROVISIONAL"), baseline_job="b", candidate_job="c")
    assert not r.promotable(v.version)[0]
    r.record_evaluation(v.version, _ev("ACCEPT_EFFICIENCY"), baseline_job="b2", candidate_job="c2", purpose="replication")
    assert r.promotable(v.version)[0]


def test_rejected_primary_closes_the_candidate():
    r = _reg()
    v = _propose(r, {"verifier_gate": "self_check"})
    r.record_evaluation(v.version, _ev("REJECT"), baseline_job="b", candidate_job="c")
    assert r.versions[v.version].status == "rejected"
    with pytest.raises(ValueError):
        r.record_evaluation(v.version, _ev("ACCEPT_QUALITY"), baseline_job="b2", candidate_job="c2", purpose="replication")


def test_candidate_of_an_old_current_must_be_reevaluated():
    r = _reg()
    a = _propose(r, {"adaptive_wait": True})
    b = _propose(r, {"verifier_gate": "self_check"})
    _accept(r, a.version, "a")
    _accept(r, b.version, "b")
    r.promote(a.version)
    ok, why = r.promotable(b.version)
    assert not ok and "not the current" in why
    c = _propose(r, {"verifier_gate": "self_check"}, parent=a.version)
    assert c.parent == a.version and c.version not in (a.version, b.version)


def test_rollback_and_withdraw():
    r = _reg()
    a = _propose(r, {"adaptive_wait": True})
    _accept(r, a.version)
    r.promote(a.version)
    assert r.rollback("regression on the held-out set") == "v0"
    assert r.current == "v0" and r.versions[a.version].status == "rolled_back"
    assert r.current_options() == effective_options(H2)
    with pytest.raises(ValueError):
        r.rollback("again")
    b = _propose(r, {"deliverable_checkpoint": True})
    r.withdraw(b.version, "headroom below the gate threshold")
    assert r.versions[b.version].status == "withdrawn" and r.log[-1]["event"] == "withdraw"
    with pytest.raises(ValueError):
        r.withdraw(b.version, "again")
    with pytest.raises(ValueError):
        r.reject("v0", "the root cannot be rejected")


def test_edits_outside_the_registry_code_are_detected(tmp_path):
    p = tmp_path / "registry.json"
    with Registry.edit(p) as r:
        r.init_root("v0", "agent", H2, rationale="H2")
    with Registry.edit(p) as r:
        _propose(r, {"adaptive_wait": True})
    d = json.loads(p.read_text())
    d["log"][0]["at"] = "2026-10-11T22:45-04:00"                          # 手改一条日志
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="changed outside"):
        Registry.load(p)


def test_text_changes_need_a_named_human_approval_before_evaluation():
    # D-089：提醒 / skill 的文字必须有人批准过；批准记下文字指纹；评测开始后不能再批
    r = _reg()
    note = {"trigger": "repeat_command", "text": "You sent the same command {n} times; change something first."}
    v = _propose(r, {"custom_notes": [note]})
    assert r.needs_text_approval(v.version)
    with pytest.raises(ValueError, match="name of the person"):
        r.approve_text(v.version, by=" ")
    r.approve_text(v.version, by="user", note="read in chat")
    assert not r.needs_text_approval(v.version) and len(r.versions[v.version].text_approval["text_hash"]) == 12
    w = _propose(r, {"adaptive_wait": True})
    assert not r.needs_text_approval(w.version)
    with pytest.raises(ValueError, match="no text"):
        r.approve_text(w.version, by="user")
    r.record_evaluation(v.version, _ev("INCONCLUSIVE"), baseline_job="b", candidate_job="c")
    with pytest.raises(ValueError, match="before evaluation"):
        r.approve_text(v.version, by="user")
