from agenteval.report.agreement import cohen_kappa, agreement
from agenteval.regression.gate import gate
from agenteval.schemas import Step, TrialRecord

def test_kappa_and_agreement():
    assert cohen_kappa(["A","B","A","B"], ["A","B","A","B"]) == 1.0
    assert abs(cohen_kappa(["A","A","B","B"], ["A","B","A","B"])) < 1e-9   # 纯随机 → 0
    x = {"t1": {"primary": "LOOP", "onset": 3}, "t2": {"primary": "CAPABILITY", "onset": 5}}
    y = {"t1": {"primary": "POLLING", "onset": 4}, "t2": {"primary": "CAPABILITY", "onset": 9}}
    r = agreement(x, y, "j1", "j2")
    assert r["n"] == 2 and r["raw_agreement"] == 0.5 and r["raw_agreement_tb_class"] == 1.0 and r["onset_within_2_steps"] == 0.5
    # 宽松口径：t1 一方把对方的主标签列为次标签 → 算一致
    x["t1"]["secondary"] = ["POLLING"]
    assert agreement(x, y, "j1", "j2")["lenient_agreement"] == 1.0

def test_gate_detects_regression():
    def mk(task, passed):
        return TrialRecord(f"{task}-{passed}", task, "c", 0, "j", "a", "m", 1.0 if passed else 0.0, "ok", None, None, 1, 0, 1.0, 0, 0, 0, 0.0, [Step(1, "agent")])
    a = [mk("anchor", True)] * 3 + [mk("fixme", False)] * 3
    b_ok = [mk("anchor", True), mk("anchor", True), mk("anchor", False)] + [mk("fixme", True)] * 3
    b_bad = [mk("anchor", False)] * 3 + [mk("fixme", True)] * 3
    assert gate(a, b_ok, ["anchor", "fixme"])["passed"]
    r = gate(a, b_bad, ["anchor", "fixme"]); assert not r["passed"] and r["failed"] == ["anchor"]
