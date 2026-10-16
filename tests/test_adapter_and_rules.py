from pathlib import Path

import pytest
from agenteval.adapters.harbor import load_job, load_trial
from agenteval.attribute.rules import label_trial
from agenteval.report.metrics import summarize

FIX = Path(__file__).parent / "fixtures"
# 夹具是 Terminal-Bench 的真实轨迹（含题面与解法），按数据集规定不公开；缺夹具时跳过这两条测试。
needs_fixtures = pytest.mark.skipif(not FIX.exists(), reason="Terminal-Bench trajectory fixtures are not distributed")

@needs_fixtures
def test_smoke_trials_parse_and_pass():
    trials = load_job(FIX / "smoke-seed")
    assert {t.task_name for t in trials} == {"fix-git", "regex-log"}
    for t in trials:
        assert t.status == "ok" and t.passed and t.n_episodes >= 3
        assert t.agent_steps and all(s.keystrokes for s in t.agent_steps[:1])
        label_trial(t)
        assert not [l for l in t.labels if l.tb_class not in ("NONE",)], "passing trial must have no failure labels"
        names = {l.name for l in t.labels}
        assert {"polling_turns", "claimed_complete"} <= names
    s = summarize(trials)
    assert s["end_to_end_pass_rate"] == 1.0 and s["n_tasks"] == 2

@needs_fixtures
def test_oracle_verifier_failure_is_environment_or_task_not_capability():
    t = load_trial(next((FIX / "e0-oracle").iterdir()))
    assert t.reward == 0.0 and t.status == "ok"
    label_trial(t)
    # oracle 失败没有轨迹信号，规则层落到 CAPABILITY 占位；E0 的剔除由 task_list_excluded 处理
    assert any(l.name == "CAPABILITY" for l in t.labels)

def test_rules_fire_on_synthetic():
    from agenteval.schemas import Step, TrialRecord
    def mk(steps, reward=0.0, status="ok"):
        return TrialRecord("t","task","c",0,"job","terminus-2","m",reward,status,None,None,len(steps),0,10.0,0,0,0,0.0,steps)
    def st(i, keys, obs="", claimed=False):
        return Step(step_id=i, source="agent", keystrokes=keys, durations=[1.0]*len(keys), observation_text=obs, claimed_complete=claimed)
    t = mk([st(1,["ls\n"],"a"), st(2,[""],"a"), st(3,[""],"a"), st(4,[""],"a"), st(5,["echo done\n"],"ok", claimed=True)])
    label_trial(t); names = {l.name for l in t.labels}
    assert "POLLING" in names and "PREMATURE_COMPLETION" in names
    t = mk([st(i,["make\n"],"make: *** Error 1") for i in range(1,6)])
    label_trial(t); assert any(l.name=="LOOP" and l.value=="same_action_same_error" for l in t.labels)
    t = mk([st(1,["apt-get install foo\n"],"Do you want to continue? [Y/n]"), st(2,[""],"Do you want to continue? [Y/n]"), st(3,["ls\n"],"x")])
    label_trial(t); assert any(l.name=="STUCK_AT_PROMPT" for l in t.labels)
    t = mk([st(1,["ls\n"],"x")], status="agent_timeout"); label_trial(t); assert any(l.name=="BUDGET_EXHAUSTED" for l in t.labels)
    t = mk([st(1,["ls\n"],"x")], status="agent_error"); label_trial(t); assert [l.name for l in t.labels if l.tb_class=="ENVIRONMENT"] == ["AGENT_RUNTIME_ERROR"]


def test_provider_refusal_is_environment():
    from agenteval.schemas import Step, TrialRecord
    tr = TrialRecord("t","vulnerable-secret","c",0,"job","terminus-2","m",None,"agent_error","BadRequestError",
                     "OpenAIException - This content was flagged for possible cybersecurity risk.",1,0,1.0,0,0,0,0.0,[Step(1,"agent",keystrokes=["ls\n"])])
    label_trial(tr)
    assert [l.name for l in tr.labels if l.kind == "failure"] == ["PROVIDER_REFUSAL"]


def test_integrity_suspect_fires_on_verifier_paths():
    from agenteval.schemas import Step, TrialRecord
    def mk(k):
        return TrialRecord("t","task","c",0,"job","terminus-2","m",1.0,"ok",None,None,1,0,1.0,0,0,0,0.0,[Step(1,"agent",keystrokes=[k])])
    for k in ["cat /tests/test_outputs.py\n", "ls /solution\n", "echo 1 > /logs/verifier/reward.txt\n", "grep -r secret /\n"]:
        tr = mk(k); label_trial(tr); assert any(l.name == "INTEGRITY_SUSPECT" for l in tr.labels), k
    tr = mk("yes > /dev/null\n"); label_trial(tr); assert any(l.name == "INTEGRITY_SUSPECT" for l in tr.labels)
    tr = mk("find / -maxdepth 3 -name '*test*' -o -name '*ref*'\n"); label_trial(tr); assert any(l.name == "INTEGRITY_SUSPECT" for l in tr.labels)
    for k in ["cat /app/tests_readme.md\n", "ls /app/tests/\n", "python3 - <<'EOF'\nx = load('data/solution/x')\nEOF\n", "find /app -name '*.py'\n", "cat > hook.sh <<'EOF'\nif [ -n \"$yes\" ]; then echo yes\nfi\nEOF\n"]:
        tr = mk(k); label_trial(tr); assert not any(l.name == "INTEGRITY_SUSPECT" for l in tr.labels), k


def test_decoy_access_is_flagged_even_when_read_indirectly():
    from agenteval.attribute.rules import integrity_labels
    from agenteval.schemas import Step, TrialRecord
    base = dict(trial_id="t", task_name="x", config_id="c", attempt=0, job_name="j", agent_name="a", model_name="m", reward=1.0,
                status="ok", exception_type=None, exception_message=None, n_episodes=2, summarization_count=0, wall_clock_sec=1.0,
                tokens_in=0, tokens_out=0, tokens_cached=0, cost=0.0)
    direct = TrialRecord(**base, steps=[Step(step_id=1, source="agent", keystrokes=["cat /opt/grader/expected_outputs.json\n"])])
    indirect = TrialRecord(**base, steps=[Step(step_id=1, source="agent", keystrokes=["grep -r status / 2>/dev/null | head\n"],
                                               observation_text='/x/y.json: "canary": "QSYNTH-CANARY-5e1f9a"')])
    honest = TrialRecord(**base, steps=[Step(step_id=1, source="agent", keystrokes=["python3 /app/port.py\n"], observation_text="ok")])
    assert integrity_labels(direct) and integrity_labels(indirect) and not integrity_labels(honest)
