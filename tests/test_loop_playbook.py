"""自进化闭环：提议模型改写 playbook 的纯函数（agenteval/loop/playbook.py，D-089）。"""
import pytest

from agenteval.loop import playbook as pb

VERSIONS = {
    "v0": {"parent": None},
    "v0+c01": {"parent": "v0", "source": "proposer:gpt-6-sol#0", "change": {"adaptive_wait": True}, "status": "withdrawn",
               "prereg": {"target_mode": "polling", "predicted_mechanism_change": "tokens down 10-16%"},
               "notes": ["headroom below the gate: empty waits are 0.045 per trial"], "evaluations": []},
    "v0+c04": {"parent": "v0", "source": "human:user", "change": {"append_nudge": True}, "status": "evaluated",
               "prereg": {"target_mode": "line_by_line_write"},
               "evaluations": [{"decision": "INVALID"}, {"decision": "INCONCLUSIVE", "pass": {"delta": 1.6}, "reasons": ["r"]}]},
}


def test_evidence_uses_predictions_and_last_valid_outcome_only():
    ev = pb.evidence(VERSIONS)
    assert [e["version"] for e in ev] == ["v0+c01", "v0+c04"]
    assert ev[0]["outcome"]["decision"] == "withdrawn" and "headroom" in ev[0]["outcome"]["reasons"][0]
    assert ev[1]["outcome"]["decision"] == "INCONCLUSIVE"
    s, u = pb.build_prompt("RULES", ev)
    assert "RULES" in u and "v0+c01" in u and "enforced in code" in u


def test_parse_and_check():
    text = '{"playbook": "Estimate headroom first.", "changes": [{"change": "c", "evidence": ["v0+c01"], "expected_effect": "e"}]}'
    obj = pb.parse(text)
    ev = pb.evidence(VERSIONS)
    assert pb.check(obj["playbook"], ev, obj["changes"], lambda t: []) == []
    bad = [{"change": "c", "evidence": ["v0+c99"]}]
    assert pb.check("x", ev, bad, lambda t: [])                                   # 引用不存在的候选
    assert pb.check("w " * 701, ev, obj["changes"], lambda t: [])                 # 太长
    assert pb.check("x", ev, obj["changes"], lambda t: ["shares a 6-word sequence with task #3: 'a b c d e f'"])
    assert pb.check("x", ev, obj["changes"], lambda t: ["mentions grading / tests / answers: 'tests'"]) == []   # playbook 可以谈测试
    assert pb.check("x", ev, obj["changes"], lambda t: ["uses an identifier that appears only in 3 of 210 tasks: 'c04'"]) == []
    assert pb.check("x", ev, obj["changes"], lambda t: ["uses an identifier that appears only in 2 of 210 tasks: 'site_id'"])
    with pytest.raises(ValueError):
        pb.parse('{"playbook": "x", "changes": []}')
