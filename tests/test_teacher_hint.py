"""实时 Teacher 提示（D-069）：纯函数、agent 接线、SFT 导出的删除规则。agent 部分需要 harbor（服务器 .venv）。"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from terminus2_patches.teacher import MARK, Breaker, parse_hint, render_view


# ---------------------------------------------------------------- 纯函数
def test_parse_hint_rules():
    assert parse_hint('{"deliver": true, "hint": "Your header lacks the events column."}', 60).text == "Your header lacks the events column."
    assert parse_hint('```json\n{"deliver": false}\n```', 60).drop_reason == "teacher_abstained"
    assert parse_hint("no json here", 60).drop_reason == "malformed"
    assert parse_hint('{"deliver": true, "hint": ""}', 60).drop_reason == "empty_hint"
    assert parse_hint('{"deliver": true, "hint": "' + "word " * 70 + '"}', 60).drop_reason.startswith("over_word_cap")
    assert parse_hint('{"deliver": true, "hint": "use ```grep```"}', 60).drop_reason == "contains_code_block"


def test_render_view_has_commands_and_output_not_reasoning():
    v = render_view([{"turn": 1, "commands": ["ls\n"], "output": "a.txt\n"},
                     {"turn": 2, "commands": [], "output": "x" * 5000}], max_out_chars=100)
    assert "$ ls" in v and "a.txt" in v and "(no command" in v and "[truncated]" in v and len(v) < 600


def test_breaker():
    b = Breaker(2)
    b.record(False); assert not b.open
    b.record(False); assert b.open
    b.record(True); assert not b.open


# ---------------------------------------------------------------- agent 接线
harbor = pytest.importorskip("harbor")
from harbor.agents.terminus_2.terminus_2 import Terminus2  # noqa: E402

from terminus2_patches.agent import Terminus2Patched  # noqa: E402


def _mk(**kw):
    return Terminus2Patched(logs_dir=Path(tempfile.mkdtemp()), model_name="openai/dummy", api_base="http://localhost:1",
                            model_info={"max_input_tokens": 1000, "max_output_tokens": 100}, suppress_max_turns_warning=True, **kw)


class FakeSession:
    def __init__(self, out="root@x:/app# "):
        self.out = out

    async def get_incremental_output(self):
        return self.out

    async def send_keys(self, *a, **k):
        return None


def _teacher(reply, calls):
    async def fake(system, user):
        calls.append(user)
        if isinstance(reply, Exception):
            raise reply
        return reply, {"prompt_tokens": 10, "completion_tokens": 5}
    return fake


def _ready(a):
    a._patched_stats = a._fresh_stats([])
    a._teacher_ctx = {"instruction": "Write /app/out.tsv", "knowledge": "SOLUTION ... TESTS ..."}
    return a


def test_teacher_off_by_default_and_counts_as_flag():
    assert _mk().all_flags_off and not _mk(teacher_hint=True).all_flags_off


def test_periodic_hint_injected_every_n_turns():
    a = _ready(_mk(teacher_hint=True, hint_every=2))
    calls = []
    a._teacher_call = _teacher('{"deliver": true, "hint": "The header misses the events column."}', calls)
    for n in (1, 2):
        a._n_episodes = n
        _, out = asyncio.run(a._execute_commands([], FakeSession()))
        if n == 1:
            assert MARK not in out and not calls
    assert out.endswith(MARK + "The header misses the events column.") and len(calls) == 1
    assert "Routine check after turn 2" in calls[0] and "SOLUTION" in calls[0]
    assert a._patched_stats["teacher"]["hints"] == [{"turn": 2, "text": "The header misses the events column.", "at_claim": False}]


def test_claim_hint_interrupts_completion_once():
    up = Terminus2(logs_dir=Path(tempfile.mkdtemp()), model_name="openai/dummy", api_base="http://localhost:1",
                   model_info={"max_input_tokens": 1000, "max_output_tokens": 100},
                   suppress_max_turns_warning=True)._get_completion_confirmation_message("S")
    a = _ready(_mk(teacher_hint=True, hint_every=100))
    calls = []
    a._teacher_call = _teacher('{"deliver": true, "hint": "Zero-delta groups are missing from your output."}', calls)
    a._n_episodes, a._claim_this_turn = 5, True
    asyncio.run(a._execute_commands([], FakeSession()))
    a._pending_completion = True                       # 上游在调用确认消息前刚设为 True
    msg = a._get_completion_confirmation_message("S")
    assert msg.endswith(MARK + "Zero-delta groups are missing from your output.") and a._pending_completion is False
    assert a._patched_stats["teacher"]["hints"][0]["at_claim"] is True
    assert a._get_completion_confirmation_message("S") == up   # 提示只用一次


def test_caps_and_teacher_errors_never_block_student():
    a = _ready(_mk(teacher_hint=True, hint_every=1, hint_max=1, teacher_max_calls=3))
    calls = []
    a._teacher_call = _teacher('{"deliver": true, "hint": "Check the rounding rule."}', calls)
    for n in (1, 2, 3):
        a._n_episodes = n
        asyncio.run(a._execute_commands([], FakeSession()))
    assert len(calls) == 1 and len(a._patched_stats["teacher"]["hints"]) == 1   # 送达 1 条后不再调用
    b = _ready(_mk(teacher_hint=True, hint_every=1, teacher_max_calls=10))
    b._teacher_call = _teacher(RuntimeError("api down"), [])
    for n in range(1, 6):
        b._n_episodes = n
        _, out = asyncio.run(b._execute_commands([], FakeSession()))
    st = b._patched_stats["teacher"]
    assert len(st["calls"]) == 3 and st["breaker_open"] and MARK not in out   # 连续 3 次失败后熔断


def test_missing_teacher_config_raises(monkeypatch, tmp_path):
    env = SimpleNamespace(environment_name="log-regex--x", trial_paths=SimpleNamespace(agent_dir=tmp_path))
    monkeypatch.delenv("TEACHER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TEACHER_API_KEY"):
        asyncio.run(_mk(teacher_hint=True).run("task", env, SimpleNamespace(metadata=None)))
    monkeypatch.setenv("TEACHER_API_KEY", "k")
    kf = tmp_path / "k.json"; kf.write_text(json.dumps({"other-task": "x"}))
    with pytest.raises(RuntimeError, match="no knowledge"):
        asyncio.run(_mk(teacher_hint=True, teacher_knowledge=str(kf)).run("task", env, SimpleNamespace(metadata=None)))


# ---------------------------------------------------------------- 导出时删除
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "train"))
from tb_sft_export import check_trial  # noqa: E402

A = lambda txt, done=False: {"role": "assistant", "content": json.dumps({"analysis": txt, "plan": "p", "commands": [], "task_complete": done})}
U = lambda txt: {"role": "user", "content": txt}


def _traj(claim_turns):
    """agent 步：第 1 轮写文件，第 2 轮运行，之后每个 claim_turns 里的轮宣布完成。"""
    steps = [{"source": "user", "message": "task"},
             {"source": "agent", "message": "w", "tool_calls": [{"function_name": "bash_command", "arguments": {"keystrokes": "cat > a.py << 'EOF'\nx\nEOF\n"}}]},
             {"source": "agent", "message": "r", "tool_calls": [{"function_name": "bash_command", "arguments": {"keystrokes": "python3 a.py\n"}}]}]
    for k in range(3, max(claim_turns) + 1):
        calls = [{"function_name": "mark_task_complete", "arguments": {}}] if k in claim_turns else []
        steps.append({"source": "agent", "message": "Analysis: done", "tool_calls": calls})
    return {"steps": steps}


def _trial(root, name, msgs, hints, traj):
    d = root / f"{name}__abc"; (d / "agent").mkdir(parents=True)
    json.dump(traj, open(d / "agent" / "trajectory.json", "w"))
    json.dump({"task_name": f"synth/{name}", "exception_info": None, "verifier_result": {"rewards": {"reward": 1.0}},
               "agent_result": {"metadata": {"all_messages": msgs, "summarization_count": 0,
                                             "patched": {"completion_gate": [], "teacher": {"hints": hints}}}}},
              open(d / "result.json", "w"))
    (d / "agent" / "raw_responses.jsonl").write_text(json.dumps({"parse_error": None, "fix": None}) + "\n")
    return d


def test_export_strips_periodic_hint(tmp_path):
    h = "Your output drops rows with empty SKU."
    msgs = [U("task"), A("look"), U("out1\n\n" + MARK + h), A("fix it"), U("out2"), A("done", True)]
    ex, why = check_trial(_trial(tmp_path, "p", msgs, [{"turn": 1, "text": h, "at_claim": False}], _traj({3})), {}, None, 0.8, True, False)
    assert why == "ok" and ex["messages"][2]["content"] == "out1" and ex["hinted"] == "teacher"


def test_export_removes_interrupted_claim_turn(tmp_path):
    h = "Zero-delta groups are missing."
    msgs = [U("task"), A("write"), U("o1"), A("run"), U("o2"), A("I am done", True), U("Current terminal state:\n$\n\n" + MARK + h),
            A("add zero groups"), U("o4"), A("done", True)]
    hints = [{"turn": 3, "text": h, "at_claim": True, "claim_had_commands": False}]
    ex, why = check_trial(_trial(tmp_path, "c", msgs, hints, _traj({3, 5})), {}, None, 0.8, True, False)
    assert why == "ok" and [m["content"] for m in ex["messages"]][4:6] == ["o2", msgs[7]["content"]]
    assert not any(MARK in m["content"] for m in ex["messages"])
    hints2 = [dict(hints[0], claim_had_commands=True)]
    assert check_trial(_trial(tmp_path, "c2", msgs, hints2, _traj({3, 5})), {}, None, 0.8, True, False)[1] == "claim_hint_after_commands"


def test_export_drops_trajectories_that_mention_the_reviewer(tmp_path):
    h = "Check the rounding rule."
    msgs = [U("task"), A("look"), U("o1\n\n" + MARK + h), A("As the reviewer said, fix rounding"), U("o2"), A("done", True)]
    assert check_trial(_trial(tmp_path, "m", msgs, [{"turn": 1, "text": h, "at_claim": False}], _traj({3})),
                       {}, None, 0.8, True, False)[1] == "mentions_teacher_hint"


def test_keep_teacher_hints_mode_keeps_notes_and_masks_interrupted_claim(tmp_path):
    h = "Zero-delta groups are missing."
    msgs = [U("task"), A("write"), U("o1"), A("run"), U("o2"), A("I am done", True), U("Current terminal state:\n$\n\n" + MARK + h),
            A("As the reviewer said, add zero groups"), U("o4"), A("done", True)]
    hints = [{"turn": 3, "text": h, "at_claim": True, "claim_had_commands": False}]
    ex, why = check_trial(_trial(tmp_path, "k", msgs, hints, _traj({3, 5})), {}, None, 0.8, True, False, keep_teacher_hints=True)
    assert why == "ok" and len(ex["messages"]) == len(msgs)
    assert ex["messages"][5].get("train") is False and MARK + h in ex["messages"][6]["content"]
    assert "train" not in ex["messages"][7]


def test_sft_train_masks_train_false_turns():
    pytest.importorskip("transformers")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "train" / "ambig"))
    import sft_train

    class Tok:   # 极简分词器：每条消息 → [角色码, 内容长度个 1]，前缀稳定
        def apply_chat_template(self, messages, tokenize=True, add_generation_prompt=False, **kw):
            ids = []
            for m in messages:
                ids += [7 if m["role"] == "user" else 9] + [1] * len(m["content"])
            return ids + ([9] if add_generation_prompt else [])
    msgs = [{"role": "user", "content": "ab"}, {"role": "assistant", "content": "cde", "train": False},
            {"role": "user", "content": "f"}, {"role": "assistant", "content": "gh"}]
    ex = sft_train.build_example(Tok(), msgs, None, None)
    sup = sum(1 for x in ex["labels"] if x != -100)
    assert sup == 2   # 只有最后一条 assistant 的 2 个 token 算 loss
