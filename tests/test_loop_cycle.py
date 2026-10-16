"""自进化闭环的命令行（tools/loop_cycle.py）：观察读 Harbor 目录、预算、出计划只写文件不启动。"""
import json
import shutil
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from agenteval.loop.state import Registry
from tools import loop_cycle as lc

FIX = Path(__file__).parent / "fixtures"
# 夹具是 Terminal-Bench 的真实轨迹（含题面与解法），按数据集规定不公开；缺夹具时跳过用到它的测试。
needs_fixtures = pytest.mark.skipif(not FIX.exists(), reason="Terminal-Bench trajectory fixtures are not distributed")
REPO = Path(__file__).resolve().parent.parent
PRE = {"target_mode": "polling", "mechanism_metric": "polling_turns", "predicted_mechanism_change": "down",
       "predicted_pass_change": "0", "falsified_if": "not lower"}


@needs_fixtures
def test_observe_reads_fixture_trials():
    rows = lc.observe_jobs(["smoke-seed"], jobs_root=FIX)
    assert len(rows) == 2 and all(r["passed"] for r in rows) and all(r["job"] == "smoke-seed" for r in rows)
    r = rows[0]
    for k in ("task", "trial", "turns", "max_turns", "tokens_in", "minutes", "n_parse_err", "rule_labels", "polling_turns",
              "no_run_before_claim", "timeout", "infra", "append_turns", "turns_after_gate", "tokens_in_after_gate"):
        assert k in r, k
    assert r["max_turns"] == 100 and r["infra"] is False and isinstance(r["no_run_before_claim"], bool)


def test_first_claim_commands_stop_at_the_first_claim():
    traj = {"steps": [
        {"source": "agent", "tool_calls": [{"function_name": "bash_command", "arguments": {"keystrokes": "cat > a.py <<'EOF'\nx=1\nEOF\n"}}]},
        {"source": "agent", "tool_calls": [{"function_name": "mark_task_complete", "arguments": {}}]},
        {"source": "agent", "tool_calls": [{"function_name": "bash_command", "arguments": {"keystrokes": "python3 a.py\n"}}]},
    ]}
    assert lc._first_claim_commands(traj) == ["cat > a.py <<'EOF'\nx=1\nEOF\n"]
    assert lc._first_claim_commands({"steps": traj["steps"][:1]}) is None


def test_budget_refuses_calls_that_could_exceed_the_cap():
    b = lc.Budget(0.10)
    assert b.allow("gpt-6-sol", prompt_chars=30_000, max_out=4000)          # ≈ $0.02 + $0.04
    b.charge("gpt-6-sol", {"prompt_tokens": 10_000, "completion_tokens": 5000})
    assert abs(b.spent - 0.07) < 1e-9
    assert not b.allow("gpt-6-sol", prompt_chars=30_000, max_out=4000)


def test_plan_writes_configs_and_never_launches(tmp_path):
    reg = Registry()
    reg.init_root("v0", "terminus2_patches.agent:Terminus2Patched",
                  {"interface_fixes": True, "completion_gate": True}, rationale="H2")
    v, errs = reg.propose("v0", {"adaptive_wait": True}, rationale="t", prereg=PRE, source="test")
    assert v and not errs
    reg.save(tmp_path / "registry.json")
    a = Namespace(registry=str(tmp_path / "registry.json"), template=str(REPO / "experiments/configs/qroll-h2-synth-train.resolved.yaml"),
                  n_tasks=74, k=4, concurrency=32, minutes_per_trial=4.8, gpu_usd_per_hour=4.6, setup_hours=0.3, only=None,
                  tag="test", out=str(tmp_path / "plans"), config_dir=str(tmp_path / "configs"), anchor_rows="/x/rows.jsonl",
                  replicate=None, rerun=None)
    lc.cmd_plan(a)
    files = sorted((tmp_path / "configs").glob("*.yaml"))
    assert [f.name for f in files] == ["loop-test-base.resolved.yaml", "loop-test-v0-c01.resolved.yaml"]
    base, cand = (yaml.safe_load(f.read_text()) for f in files)
    for cfg in (base, cand):
        kw = cfg["agents"][0]["kwargs"]
        assert cfg["n_attempts"] == 4 and cfg["orchestrator"]["n_concurrent_trials"] == 16
        assert kw["raw_log"] is True and kw["max_turns"] == 100 and kw["api_base"].endswith("/v1")
        assert "store_all_messages" not in kw and not any(k.startswith(("teacher", "hint")) for k in kw)
        assert cfg["agents"][0]["model_name"] == "openai/coder30b"
    assert base["agents"][0]["kwargs"]["adaptive_wait"] is False and cand["agents"][0]["kwargs"]["adaptive_wait"] is True
    plan = (tmp_path / "plans" / "plan-test.md").read_text()
    assert "bash tools/launch_job.sh loop-test-base loop-test-v0-c01" in plan and "--anchor-rows /x/rows.jsonl" in plan  # 一条命令同时启动
    side = json.loads((tmp_path / "configs" / "loop-test-v0-c01.loop.json").read_text())
    assert side["purpose"] == "primary" and side["n_comparisons"] == 1 and side["baseline_job"] == "loop-test-base" and side["gate_code"]
    assert not (REPO / "experiments/configs/loop-test-base.resolved.yaml").exists()


def test_plan_retest_joins_new_candidates_and_needs_a_changed_gate(tmp_path):
    # D-088：主评测 INCONCLUSIVE 的版本可以和新候选放进同一批重测；判分代码没变、没写理由都不行
    reg = Registry()
    reg.init_root("v0", "terminus2_patches.agent:Terminus2Patched",
                  {"interface_fixes": True, "completion_gate": True}, rationale="H2")
    old, _ = reg.propose("v0", {"append_nudge": True}, rationale="t", prereg=PRE, source="test")
    reg.record_evaluation(old.version, {"decision": "INCONCLUSIVE", "reasons": []}, baseline_job="b1", candidate_job="c1",
                          extra={"gate_code": "old-gate"})
    new, _ = reg.propose("v0", {"adaptive_wait": True}, rationale="t", prereg=PRE, source="test")
    reg.save(tmp_path / "registry.json")

    def plan(tag, **kw):
        a = Namespace(registry=str(tmp_path / "registry.json"), template=str(REPO / "experiments/configs/qroll-h2-synth-train.resolved.yaml"),
                      n_tasks=74, k=4, concurrency=16, minutes_per_trial=4.8, gpu_usd_per_hour=4.6, setup_hours=0.3, only=None,
                      tag=tag, out=str(tmp_path / "plans"), config_dir=str(tmp_path / "configs"), anchor_rows="/x/rows.jsonl",
                      replicate=None, rerun=None, **kw)
        lc.cmd_plan(a)

    with pytest.raises(SystemExit, match="--reason"):
        plan("t1", retest=old.version, reason=None)
    plan("t2", retest=old.version, reason="D-088")
    sides = {p.name: json.loads(p.read_text()) for p in (tmp_path / "configs").glob("loop-t2-*.loop.json")}
    assert set(sides) == {"loop-t2-base.loop.json", f"loop-t2-{new.version.replace('+', '-')}.loop.json",
                          f"loop-t2-{old.version.replace('+', '-')}.loop.json"}
    s_old = sides[f"loop-t2-{old.version.replace('+', '-')}.loop.json"]
    s_new = sides[f"loop-t2-{new.version.replace('+', '-')}.loop.json"]
    assert s_old["purpose"] == "retest" and s_old["decision_ref"] == "D-088" and s_new["purpose"] == "primary"
    assert s_old["n_comparisons"] == 2 == s_new["n_comparisons"]                         # 重测也算进 K
    cfg = yaml.safe_load((tmp_path / "configs" / "loop-t2-base.resolved.yaml").read_text())
    assert cfg["orchestrator"]["n_concurrent_trials"] == 5                               # 总并发 16，三臂平分
    reg2 = Registry.load(tmp_path / "registry.json")
    with Registry.edit(tmp_path / "registry.json") as r:
        r.versions[old.version].evaluations[0]["gate_code"] = lc.code_hash(*lc.GATE_CODE)
    with pytest.raises(SystemExit, match="has not changed"):
        plan("t3", retest=old.version, reason="D-088")
    assert reg2.versions[old.version].status == "evaluated"


def _fake_job(root, job, start, minutes):
    d = root / job / "t1__abc"
    d.mkdir(parents=True)
    end = f"2026-10-12T{int(start[:2]) + minutes // 60:02d}:{int(start[3:]) + minutes % 60:02d}:00+00:00"
    (d / "result.json").write_text(json.dumps({"agent_execution": {"started_at": f"2026-10-12T{start}:00+00:00", "finished_at": end}}))


def test_concurrency_is_read_from_the_trials_not_declared(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "JOBS", tmp_path)
    _fake_job(tmp_path, "a", "10:00", 120)
    _fake_job(tmp_path, "b", "10:05", 120)
    _fake_job(tmp_path, "c", "13:00", 120)
    assert lc.concurrency(["a"], ["b"])[0] is True
    ok, info = lc.concurrency(["a"], ["c"])
    assert ok is False and info["start_gap_min"] == 180.0


def test_evaluate_refuses_runs_not_written_by_plan(tmp_path):
    a = Namespace(baseline_job="nope-base", candidate_job="nope-cand", version="v0+c01", anchor_rows="/x", registry=str(tmp_path / "r.json"))
    with pytest.raises(SystemExit, match="only accepts runs written by"):
        lc.cmd_evaluate(a)


@needs_fixtures
def test_missing_results_count_as_infra_and_harness_crashes_as_failures(tmp_path):
    shutil.copytree(FIX / "smoke-seed", tmp_path / "job")
    trials = sorted(p for p in (tmp_path / "job").iterdir() if p.is_dir())
    (trials[0] / "result.json").unlink()                                       # 判分结果丢了
    r = json.loads((trials[1] / "result.json").read_text())                   # 我们自己的代码崩了
    r["exception_info"] = {"exception_type": "KeyError", "exception_message": "'x'",
                           "exception_traceback": 'Traceback:\n  File "/root/work/agent_harness/terminus2_patches/agent.py", line 3, in run\nKeyError'}
    r["verifier_result"] = {"rewards": {"reward": 0.0}}
    (trials[1] / "result.json").write_text(json.dumps(r))
    rows = {x["trial"]: x for x in lc.observe_jobs(["job"], jobs_root=tmp_path)}
    assert rows[trials[0].name]["infra"] is True and rows[trials[0].name]["error_kind"] == "missing_result"
    assert rows[trials[1].name]["infra"] is False and rows[trials[1].name]["error_kind"] == "harness_error"



def test_plan_refuses_candidates_whose_text_nobody_approved(tmp_path):
    reg = Registry()
    reg.init_root("v0", "terminus2_patches.agent:Terminus2Patched",
                  {"interface_fixes": True, "completion_gate": True}, rationale="H2")
    note = {"trigger": "turn_budget", "text": "Half of your turns are used; write the deliverable now and refine it after."}
    v, errs = reg.propose("v0", {"custom_notes": [note]}, rationale="t", prereg=PRE, source="test")
    assert v and not errs
    reg.save(tmp_path / "registry.json")
    a = Namespace(registry=str(tmp_path / "registry.json"), template=str(REPO / "experiments/configs/qroll-h2-synth-train.resolved.yaml"),
                  n_tasks=74, k=4, concurrency=16, minutes_per_trial=4.8, gpu_usd_per_hour=4.6, setup_hours=0.3, only=None,
                  tag="tx", out=str(tmp_path / "plans"), config_dir=str(tmp_path / "configs"), anchor_rows="/x/rows.jsonl",
                  replicate=None, rerun=None)
    with pytest.raises(SystemExit, match="not yet approved"):
        lc.cmd_plan(a)
    with Registry.edit(tmp_path / "registry.json") as r:
        r.approve_text(v.version, by="user")
    lc.cmd_plan(a)
    cfg = yaml.safe_load((tmp_path / "configs" / f"loop-tx-{v.version.replace('+', '-')}.resolved.yaml").read_text())
    assert cfg["agents"][0]["kwargs"]["custom_notes"] == [{"text": note["text"], "trigger": "turn_budget"}]
    base = yaml.safe_load((tmp_path / "configs" / "loop-tx-base.resolved.yaml").read_text())
    assert base["agents"][0]["kwargs"]["custom_notes"] == [] and base["agents"][0]["kwargs"]["skills"] == []


def test_screen_texts_blocks_task_specific_and_grading_text():
    tasks = ["Write /app/report.csv with columns site_id,count. All responses end with a single trailing newline."] * 3 + ["other"] * 40
    ok = {"custom_notes": [{"trigger": "repeat_command", "text": "You repeated the same command; change one thing before retrying."}]}
    assert lc.screen_texts(ok, tasks) == []
    leak = {"skills": [{"name": "csv-help", "description": "for site_id reports", "body": "Run the tests before finishing."}]}
    probs = lc.screen_texts(leak, tasks)
    assert any("site_id" in p for p in probs) and any("tests" in p for p in probs)


def test_replication_can_be_planned_after_an_accepting_retest(tmp_path):
    reg = Registry()
    reg.init_root("v0", "terminus2_patches.agent:Terminus2Patched",
                  {"interface_fixes": True, "completion_gate": True}, rationale="H2")
    v, _ = reg.propose("v0", {"append_nudge": True}, rationale="t", prereg=PRE, source="test")
    reg.record_evaluation(v.version, {"decision": "INCONCLUSIVE", "reasons": []}, baseline_job="b1", candidate_job="c1",
                          extra={"gate_code": "old"})
    reg.save(tmp_path / "registry.json")
    a = Namespace(registry=str(tmp_path / "registry.json"), template=str(REPO / "experiments/configs/qroll-h2-synth-train.resolved.yaml"),
                  n_tasks=74, k=4, concurrency=16, minutes_per_trial=4.8, gpu_usd_per_hour=4.6, setup_hours=0.3, only=None,
                  tag="rp", out=str(tmp_path / "plans"), config_dir=str(tmp_path / "configs"), anchor_rows="/x/rows.jsonl",
                  replicate=v.version, rerun=None)
    with pytest.raises(SystemExit, match="cannot be replicated"):
        lc.cmd_plan(a)
    with Registry.edit(tmp_path / "registry.json") as r:
        r.record_evaluation(v.version, {"decision": "ACCEPT_EFFICIENCY", "reasons": []}, baseline_job="b2", candidate_job="c2",
                            purpose="retest", extra={"gate_code": "new", "decision_ref": "D-088"})
    lc.cmd_plan(a)
    side = json.loads((tmp_path / "configs" / f"loop-rp-{v.version.replace('+', '-')}.loop.json").read_text())
    assert side["purpose"] == "replication"
