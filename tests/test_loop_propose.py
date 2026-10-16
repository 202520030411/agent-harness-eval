"""自进化闭环：提议模型的提示、解析与预注册检查（agenteval/loop/propose.py）。"""
import json

import pytest

from agenteval.loop.propose import METRICS, build_prompt, check_candidate, mechanism_direction, parse_response, prereg_of

GOOD = {"changes": {"adaptive_wait": True}, "target_mode": "polling", "mechanism": "returns as soon as the command finishes",
        "mechanism_metric": "polling_turns", "predicted_mechanism_change": "decrease by ~30%", "predicted_pass_change": "0 to +2 pp",
        "falsified_if": "polling_turns not lower", "why_now": "never tried on Qwen", "risk": "cuts off slow builds"}


def test_parse_response_tolerates_fences_prose_and_braces_in_strings():
    obj = {"auto_candidates": [GOOD], "review_proposals": [], "rejected_ideas": [{"idea": "use {curly} braces", "why": "a \"quote\""}]}
    text = "Here is my answer:\n```json\n" + json.dumps(obj) + "\n```\nHope this helps {not json}."
    assert parse_response(text) == obj
    assert parse_response('{broken: 1} then {"auto_candidates": [], "x": {"b": 2}}') == {"auto_candidates": [], "x": {"b": 2}}
    with pytest.raises(ValueError):                                          # 被截断：不能把里面的候选当成答案
        parse_response('{"auto_candidates": [{"changes": {"adaptive_wait": true}, "target_mode": "polling"}, {"changes":')
    with pytest.raises(ValueError):                                          # 前面举例的小对象不是答案
        parse_response('For example {"changes": {"a": 1}} is a candidate.')
    with pytest.raises(ValueError):
        parse_response("no json at all")
    with pytest.raises(ValueError):
        parse_response("[1, 2, 3]")


def test_check_candidate_requires_target_metric_and_predictions():
    assert check_candidate(GOOD, {"polling", "timeout"}) == []
    errs = check_candidate({**GOOD, "target_mode": "loop", "mechanism_metric": "happiness", "falsified_if": " "}, {"polling"})
    assert len(errs) == 3
    assert check_candidate({**GOOD, "changes": {}}, {"polling"}) == ["changes must be a non-empty object"]
    assert check_candidate({**GOOD, "target_mode": ["polling", "timeout"]}, {"polling"})          # 列表不能让它崩溃
    assert check_candidate("not a dict", {"polling"}) == ["candidate is not a JSON object"]
    assert check_candidate({**GOOD, "predicted_pass_change": 0}, {"polling"}) == []


def test_prereg_keeps_only_the_registered_fields():
    p = prereg_of({**GOOD, "extra": 1})
    assert "extra" not in p and "changes" not in p and p["mechanism_metric"] == "polling_turns"


def test_mechanism_direction():
    assert mechanism_direction(GOOD) == "decrease"
    assert mechanism_direction({"predicted_mechanism_change": "should increase slightly"}) == "increase"
    assert mechanism_direction({"predicted_mechanism_change": "上升 10%"}) == "increase"
    assert mechanism_direction({"predicted_mechanism_change": "fewer turns"}) == "decrease"
    assert mechanism_direction({}) == "decrease"
    for text in ("reduces polling turns by 25% or more", "append_turns should drop by 30% or more", "cut by up to 40%",
                 "-30% or more", "decreased by 30%, more on long tasks"):
        assert mechanism_direction({"predicted_mechanism_change": text}) == "decrease", text


def test_build_prompt_carries_scope_targets_history_and_limits():
    targets = [{"mode": "polling", "label": "x", "among": "failed", "prior": "HARNESS", "evidence": "e", "levers": ["adaptive_wait"],
                "n": 12, "denominator": 80, "rate": 0.15, "share_of_failures": 0.15, "n_tasks": 7, "tried": [], "examples": ["secret"]}]
    history = [{"id": "E4-adaptive-wait", "switches": "adaptive_wait", "pass_delta_pp": 0.0, "private_note": "drop me"}]
    previous = [{"version": "v0+c01", "status": "withdrawn", "change": {"adaptive_wait": True}, "notes": ["headroom below the gate"]}]
    system, user = build_prompt({"interface_fixes": True}, targets, history, {"model": "Qwen3-Coder-30B"}, k_auto=2, k_review=1,
                                previous=previous)
    assert "headroom below the gate" in user and "PREVIOUS CANDIDATES" in user
    assert "harness" in system
    assert "At most 2 AUTO candidates and 1 REVIEW proposals" in user
    assert "wait_cap_sec" in user and "E4-adaptive-wait" in user and "Qwen3-Coder-30B" in user
    assert "drop me" not in user and "secret" not in user                         # 只给提议模型需要的字段
    assert all(k in user for k in METRICS)
