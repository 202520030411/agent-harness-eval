"""自进化闭环：自动找毛病的纯函数（agenteval/loop/discover.py，D-089）。"""
import pytest

from agenteval.loop import discover as dc


def _rows():
    rows = []
    for t in range(10):
        for i in range(4):
            rows.append({"task": f"t{t}", "trial": f"t{t}__{i}", "passed": (t < 3 and i == 0), "infra": False})
    rows.append({"task": "t9", "trial": "t9__x", "passed": False, "infra": True})
    return rows


def test_pick_trials_spreads_over_tasks_and_adds_contrast_for_mixed_tasks():
    picks = dc.pick_trials(_rows(), n=12, seed=1)
    assert len(picks) == 12 and len({p["task"] for p in picks[:10]}) == 10          # 先每题一条
    assert all(p["trial"] != "t9__x" for p in picks)                               # 故障不算
    for p in picks:
        assert (p["contrast"] is not None) == (p["task"] in ("t0", "t1", "t2"))
    assert dc.pick_trials(_rows(), n=12, seed=1) == picks                          # 固定种子，结果可复现


def test_condense_keeps_head_and_tail_in_full_and_middle_as_commands():
    steps = [{"source": "user", "message": "sys"}]
    for i in range(40):
        steps.append({"source": "agent", "message": f"thinking {i}",
                      "tool_calls": [{"function_name": "bash_command", "arguments": {"keystrokes": f"cmd{i}\n"}}],
                      "observation": {"results": [{"content": f"output {i}"}]}})
    text = dc.condense({"steps": steps}, head=2, tail=3)
    lines = text.splitlines()
    assert len(lines) == 40 and "out:" in lines[0] and "out:" not in lines[10] and "out:" in lines[-1]


def test_parse_judgement_and_agreement():
    a = dc.parse_judgement('```json\n{"category": "new", "new_category": "Bad Name!", "behavior": "x", "harness_fixable": "Yes"}\n```')
    assert a["new_category"] == "unnamed" and a["harness_fixable"] == "yes"
    with pytest.raises(ValueError):
        dc.parse_judgement('{"category": "line_by_line_write", "behavior": "x", "harness_fixable": "no"}')   # 找回测试：不在清单里
    b = dc.parse_judgement('{"category": "loop", "behavior": "y", "harness_fixable": "no"}')
    assert dc.agree(a, a)["status"] == "new" and dc.agree(b, b)["status"] == "known" and dc.agree(a, b)["status"] == "disputed"
    assert dc.agree(a, None)["status"] == "judge_failed"
    assert dc.HELD_OUT_MODE not in dc.KNOWN_EN


def test_parse_clusters_assigns_each_item_once():
    text = '{"categories": [{"name": "a", "definition": "d", "items": [1, 2, 2, 9]}, {"name": "b", "items": [2, 3]}]}'
    cs = dc.parse_clusters(text, n_items=3)
    assert cs[0]["items"] == [1, 2] and cs[1]["items"] == [3]


def test_rediscovery_recall():
    items = [{"behaviors": ["wrote the file one line per turn with echo >>", "ran out of turns"], "truth": True},
             {"behaviors": ["ran out of turns", "ran out of turns"], "truth": True},
             {"behaviors": ["did not check output", "x"], "truth": False}]
    r = dc.rediscovered_append([], items)
    assert r["n_truth"] == 2 and r["recall"] == 0.5 and r["found"] and r["mentions_on_other_trials"] == 0
