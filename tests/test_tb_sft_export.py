"""train/tb_sft_export.py：rollout → SFT 样本的筛选规则（QWEN_PLAN §4）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "train"))
from tb_sft_export import check_trial  # noqa: E402

HINT = "Hint: before finishing, run python3 check.py and make sure every line says PASS."
MSGS = [{"role": "user", "content": "Task: build the tool.\n\n" + HINT + "\n\nCurrent terminal state: $"},
        {"role": "assistant", "content": '{"analysis": "start", "plan": "look", "commands": [{"keystrokes": "ls\\n", "duration": 0.1}]}'},
        {"role": "user", "content": "New Terminal Output: check.py"},
        {"role": "assistant", "content": '{"analysis": "done", "plan": "finish", "commands": [], "task_complete": true}'}]


def _traj(cmds_before_claim, claim_msg="Analysis: done\nPlan: finish"):
    steps = [{"source": "user", "message": "task"}]
    for k in cmds_before_claim:
        steps.append({"source": "agent", "message": "Analysis: working", "tool_calls": [{"function_name": "bash_command", "arguments": {"keystrokes": k}}]})
    steps.append({"source": "agent", "message": claim_msg, "tool_calls": [{"function_name": "mark_task_complete", "arguments": {}}]})
    return {"steps": steps}


GOOD = _traj(["cat > s.py << 'EOF'\nprint(1)\nEOF\n", "python3 s.py\n"])


def _trial(root: Path, name: str, reward=1.0, exc=None, msgs=MSGS, summ=0, gate=(), raw=({"parse_error": None, "fix": None},), traj=GOOD):
    d = root / f"{name}__abc"
    (d / "agent").mkdir(parents=True)
    json.dump(traj, open(d / "agent" / "trajectory.json", "w"))
    json.dump({"task_name": f"synth/{name}", "exception_info": exc, "verifier_result": {"rewards": {"reward": reward}},
               "agent_result": {"metadata": {"all_messages": list(msgs), "summarization_count": summ,
                                             "patched": {"completion_gate": list(gate)}}}}, open(d / "result.json", "w"))
    with open(d / "agent" / "raw_responses.jsonl", "w") as f:
        for row in raw:
            f.write(json.dumps(row) + "\n")
    return d


def _check(d, hints=None, rubric=None, allow_fixed=False, keep_gated=False):
    return check_trial(d, hints or {}, rubric, 0.8, allow_fixed, keep_gated)


def test_keeps_clean_passing_trial_verbatim(tmp_path):
    ex, why = _check(_trial(tmp_path, "t1"))
    assert why == "ok" and ex["messages"] == MSGS and not ex["hinted"]


def test_drop_reasons(tmp_path):
    assert _check(_trial(tmp_path, "fail", reward=0.0))[1] == "not_passed"
    assert _check(_trial(tmp_path, "err", exc={"exception_type": "X"}))[1] == "infra_error"
    assert _check(_trial(tmp_path, "summ", summ=1))[1] == "summarized"
    assert _check(_trial(tmp_path, "gate", gate=[{"turn": 3}]))[1] == "gated"
    assert _check(_trial(tmp_path, "gate2", gate=[{"turn": 3}]), keep_gated=True)[1] == "ok"
    assert _check(_trial(tmp_path, "perr", raw=[{"parse_error": "ERROR: Invalid JSON", "fix": None}]))[1] == "parse_error"
    fixed = _trial(tmp_path, "fixed", raw=[{"parse_error": None, "fix": "ctrl"}])
    assert _check(fixed)[1] == "lenient_fixed" and _check(fixed, allow_fixed=True)[1] == "ok"
    assert _check(_trial(tmp_path, "rub"), rubric={"rub__abc": 0.5})[1] == "rubric"
    assert _check(_trial(tmp_path, "rub2"), rubric={"rub2__abc": 0.9})[1] == "ok"


def test_hint_removed_from_first_user_message(tmp_path):
    ex, why = _check(_trial(tmp_path, "h"), hints={"h": HINT})
    assert why == "ok" and ex["hinted"] and HINT not in ex["messages"][0]["content"]
    assert ex["messages"][0]["content"].startswith("Task: build the tool.") and ex["messages"][1:] == MSGS[1:]


def test_hint_echo_is_dropped(tmp_path):
    echo = [dict(m) for m in MSGS]
    echo[1] = {"role": "assistant", "content": '{"analysis": "The note says run python3 check.py and make sure every line says PASS", '
                                               '"plan": "p", "commands": []}'}
    assert _check(_trial(tmp_path, "e", msgs=echo), hints={"e": HINT})[1] == "echoes_hint"
    missing = [dict(m) for m in MSGS]
    missing[0] = {"role": "user", "content": "Task without the hint"}
    assert _check(_trial(tmp_path, "m", msgs=missing), hints={"m": HINT})[1] == "hint_not_found"


def test_claim_behavior_filters(tmp_path):
    unverified = _traj(["python3 s.py\n", "cat > out.txt << 'EOF'\n42\nEOF\n", "echo '✓ done'\n"])
    assert _check(_trial(tmp_path, "u", traj=unverified))[1] == "unverified_claim"
    admits = _traj(["python3 s.py\n"], claim_msg="Analysis: Although I couldn't make the tests pass, the file exists.\nPlan: finish")
    assert _check(_trial(tmp_path, "a", traj=admits))[1] == "admits_failure"
    assert _check(_trial(tmp_path, "n", traj={"steps": [{"source": "user", "message": "t"}]}))[1] == "no_claim"


def test_hint_mentioned_is_dropped(tmp_path):
    ment = [dict(m) for m in MSGS]
    ment[3] = {"role": "assistant", "content": '{"analysis": "As the hint says, I ran the check.", "plan": "p", "commands": [], "task_complete": true}'}
    assert _check(_trial(tmp_path, "mh", msgs=ment), hints={"mh": HINT})[1] == "mentions_hint"
