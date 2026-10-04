"""D-072 PSP 式开头规则：解析、泄题检查、失败记录视图、试点报告里的测试通过比例。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from train.synth.psp_rules import (HEADER, RULE_WORDS, attempt_view, drop_leaks, failed_trials, parse_rules,  # noqa: E402
                                   render_block)
from tools.psp_pilot_report import passed_share  # noqa: E402

GOOD = """Diagnosis: they never kept zero groups.
<skills>
1. Keep groups whose delta is zero; every earlier attempt dropped them.
2) Sort by the key the task names, not by insertion order.
- Before finishing, run your script on the sample input and compare the header.
</skills>"""


def test_parse_rules_accepts_numbered_and_bulleted():
    rules, why = parse_rules(GOOD)
    assert why is None and len(rules) == 3 and rules[1].startswith("Sort by the key")


def test_parse_rules_rejects_bad_replies():
    assert parse_rules("no block")[1] == "no_skills_block"
    assert parse_rules("<skills>\n1. a\n```sh\nls\n```\n</skills>")[1] == "contains_code_block"
    assert parse_rules("<skills>\n1. only one rule\n</skills>")[1] == "too_few_rules(1)"
    long = " ".join(["word"] * (RULE_WORDS + 1))
    rules, why = parse_rules(f"<skills>\n1. {long}\n2. a b\n3. c d\n4. e f\n</skills>")
    assert why is None and rules == ["a b", "c d", "e f"]          # 单条超长的丢掉，其余照用


def test_parse_rules_caps_count_and_total_words():
    body = "\n".join(f"{i}. " + " ".join(["w"] * 34) for i in range(1, 9))
    rules, why = parse_rules(f"<skills>\n{body}\n</skills>")
    assert why is None and len(rules) == 5                          # 34 词 × 5 = 170 ≤ 180，第 6 条会超总词数


def test_drop_leaks_removes_rules_copying_privileged_text():
    priv = "assert df groupby region sum revenue equals the value in expected totals file exactly"
    rules = ["Group by region and sum revenue equals the value in expected totals file", "Check the header line."]
    keep, n = drop_leaks(rules, priv)
    assert n == 1 and keep == ["Check the header line."]


def test_render_block_is_prefix_with_numbered_rules():
    b = render_block(["x", "y", "z"])
    assert b.startswith(HEADER) and "<skills>\n1. x\n2. y\n3. z\n</skills>" in b and b.endswith("\n\n")


def _trial(root: Path, name: str, reward: float, exc: str | None = None, pytest_tail: str = "1 failed, 3 passed in 0.2s"):
    d = root / name; (d / "agent").mkdir(parents=True); (d / "verifier").mkdir()
    json.dump({"task_name": f"synth/{name.split('__')[0]}", "verifier_result": {"rewards": {"reward": reward}},
               "exception_info": {"exception_type": exc} if exc else None}, open(d / "result.json", "w"))
    steps = [{"source": "user", "message": "task"},
             {"source": "agent", "message": "SECRET REASONING", "tool_calls": [{"function_name": "bash_command", "arguments": {"keystrokes": "ls /app\n"}}],
              "observation": {"results": [{"content": "data.csv\n"}]}}]
    json.dump({"steps": steps}, open(d / "agent" / "trajectory.json", "w"))
    (d / "verifier" / "test-stdout.txt").write_text(f"FAILED test_outputs.py::test_zero_groups\n{pytest_tail}\n")
    return d


def test_attempt_view_shows_commands_output_tests_not_reasoning(tmp_path):
    v = attempt_view(_trial(tmp_path, "t1__a", 0.0))
    assert "$ ls /app" in v and "data.csv" in v and "test_zero_groups" in v and "SECRET REASONING" not in v


def test_failed_trials_skips_passes_and_infra_errors(tmp_path):
    j = tmp_path / "job"
    _trial(j, "t1__a", 0.0); _trial(j, "t1__b", 1.0); _trial(j, "t1__c", 0.0, exc="DockerError")
    _trial(j, "t1__d", 0.0, exc="AgentTimeoutError"); _trial(j, "t2__a", 0.0)
    assert [p.name for p in failed_trials("t1", [str(j)], 6)] == ["t1__a", "t1__d"]


def test_failed_trials_matches_truncated_trial_folder_names(tmp_path):
    """Harbor 把目录名里的题名截到 32 个字符；要按 result.json 的 task_name 认题。"""
    task = "data-transform--bus-stop-departure-board"
    d = _trial(tmp_path / "job", f"{task[:32]}__x", 0.0)
    json.dump({"task_name": f"synth/{task}", "verifier_result": {"rewards": {"reward": 0.0}}, "exception_info": None}, open(d / "result.json", "w"))
    assert [p.name for p in failed_trials(task, [str(tmp_path / "job")], 6)] == [f"{task[:32]}__x"]


def test_tests_frac_reads_pytest_summary(tmp_path):
    assert passed_share(_trial(tmp_path, "t1__a", 0.0)) == 0.75
    assert passed_share(_trial(tmp_path, "t1__b", 0.0, pytest_tail="2 failed, 1 passed, 1 error in 1.0s")) == 0.25
    assert passed_share(_trial(tmp_path, "t1__c", 0.0, pytest_tail="no summary")) is None


class _FakeClient:
    def __init__(self, replies):
        self.replies, self.usage = replies, {"prompt_tokens": 100, "completion_tokens": 10}

    def complete(self, system, user):
        assert "FAILED ATTEMPT 1" in user and "PRIVILEGED" in user
        return self.replies.pop(0)


def test_rules_for_task_retries_once_then_accepts(tmp_path):
    from train.synth.psp_rules import rules_for_task
    replies = ["no block at all", GOOD]
    rec, used = rules_for_task("t1", "Write /app/out.csv", "SOLUTION ...", [_trial(tmp_path, "t1__a", 0.0)], lambda: _FakeClient(replies))
    assert rec["tries"] == 2 and rec["reason"] is None and len(rec["rules"]) == 3 and used["prompt_tokens"] == 200


def test_rules_for_task_without_failures_or_over_budget_writes_nothing(tmp_path):
    from train.synth.psp_rules import rules_for_task
    assert rules_for_task("t1", "x", "k", [], lambda: _FakeClient([GOOD]))[0]["reason"] == "no_failed_attempts_found"
    rec, _ = rules_for_task("t1", "x", "k", [_trial(tmp_path, "t1__a", 0.0)], lambda: _FakeClient([GOOD]), over_budget=lambda: True)
    assert rec["reason"] == "budget_stop" and rec["tries"] == 0


def test_mentions_hint_flags_reviewer_references(tmp_path):
    from tools.qeval_report import mentions_hint
    d = tmp_path / "t__a"; (d / "agent").mkdir(parents=True)
    json.dump({"steps": [{"source": "user", "message": "Notes from a reviewer ..."},
                         {"source": "agent", "message": "Listing files first."}]}, open(d / "agent" / "trajectory.json", "w"))
    assert mentions_hint(d) is False                      # 只看模型自己的回复，题面里的 reviewer 不算
    json.dump({"steps": [{"source": "agent", "message": "As the reviewer pointed out, fix rounding."}]}, open(d / "agent" / "trajectory.json", "w"))
    assert mentions_hint(d) is True


def test_paired_rate_delta_uses_only_tasks_with_subset_rows():
    from tools.qeval_report import paired_rate_delta
    a = [{"task": "t1", "m2": True}, {"task": "t1", "m2": False}, {"task": "t2", "m2": None}]
    b = [{"task": "t1", "m2": False}, {"task": "t1", "m2": False}, {"task": "t2", "m2": True}]
    d, lo, hi, n = paired_rate_delta(a, b, "m2", lambda r: r["m2"] is not None)
    assert n == 1 and d == -50.0 and lo == hi == -50.0     # t2 在 a 里没有“宣布过完成”的 trial，不参与配对
