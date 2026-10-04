"""不变量 1：所有开关关闭时，fork 与上游 Terminus 2 的提示词与行为一致。
需要 harbor 可导入（服务器 .venv 里装了 harbor==0.23.0）；本地没有就跳过。"""
import tempfile
from pathlib import Path

import pytest

harbor = pytest.importorskip("harbor")
from harbor.agents.terminus_2.terminus_2 import Terminus2  # noqa: E402

from terminus2_patches.agent import Terminus2Patched, Terminus2PatchedOptions  # noqa: E402


def _mk(cls, **kw):
    return cls(logs_dir=Path(tempfile.mkdtemp()), model_name="openai/dummy", api_base="http://localhost:1",
               model_info={"max_input_tokens": 1000, "max_output_tokens": 100}, suppress_max_turns_warning=True, **kw)


def test_defaults_all_off_and_prompts_identical():
    up, pa = _mk(Terminus2), _mk(Terminus2Patched)
    assert pa.all_flags_off
    assert pa._prompt_template == up._prompt_template
    assert pa._timeout_template == up._timeout_template
    assert pa._get_completion_confirmation_message("X") == up._get_completion_confirmation_message("X")
    assert pa._limit_output_length("a" * 20000) == up._limit_output_length("a" * 20000)


def test_contract_template_only_when_flag_on():
    up, pa = _mk(Terminus2), _mk(Terminus2Patched, task_contract=True)
    assert pa._prompt_template != up._prompt_template and "requirements" in pa._prompt_template
    assert "{instruction}" in pa._prompt_template and "{terminal_state}" in pa._prompt_template


def test_flags_are_accepted_and_validated():
    pa = _mk(Terminus2Patched, verifier_gate="grader_check", adaptive_wait=True, deliverable_checkpoint=True)
    assert not pa.all_flags_off and pa.options.verifier_gate == "grader_check" and pa.options.deliverable_checkpoint
    with pytest.raises(Exception):
        Terminus2PatchedOptions(verifier_gate="bogus")



def _fake_llm_call(text):
    """顶替 self._llm.call：返回 LLMResponse 形状的对象（content + usage）。"""
    from types import SimpleNamespace
    async def fake(prompt, message_history=(), **kw):
        assert message_history and message_history[0]["role"] == "system" and prompt.startswith("INSTRUCTION:")
        return SimpleNamespace(content=text, usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, cost_usd=0.001))
    return fake


@pytest.mark.parametrize("reply,on", [("intent_clarity: 2\ntarget_certainty: 0\nmissing: x", True),
                                      ("intent_clarity: 1\ntarget_certainty: 1\nmissing: none", False),
                                      ("garbled", False)])
def test_conditional_contract_picks_template_before_run(monkeypatch, reply, on):
    """H17：开跑前评分决定整道题用契约模板还是上游模板；run 结束后模板复原，评分 token 计入 trial。"""
    import asyncio
    from types import SimpleNamespace
    seen = {}
    async def fake_run(self, instruction, environment, context):
        seen.update(template=self._prompt_template, active=self._contract_active)
        context.n_input_tokens, context.n_output_tokens, context.cost_usd = 1000, 200, 0.01
    monkeypatch.setattr(Terminus2, "run", fake_run)
    up = _mk(Terminus2)._prompt_template
    pa = _mk(Terminus2Patched, task_contract=True, contract_conditional=True)
    monkeypatch.setattr(pa._llm, "call", _fake_llm_call(reply))
    contract = pa._prompt_template
    ctx = SimpleNamespace(metadata=None, n_input_tokens=None, n_output_tokens=None, cost_usd=None)
    asyncio.run(pa.run("Write /app/out.txt", None, ctx))
    assert seen["active"] is on and seen["template"] == (contract if on else up)
    assert pa._prompt_template == contract                      # 下一个 trial 重新判定
    assert ctx.metadata["patched"]["contract_gate"]["on"] is on
    assert (ctx.n_input_tokens, ctx.n_output_tokens) == (1100, 250) and abs(ctx.cost_usd - 0.011) < 1e-9


def test_conditional_gate_error_falls_back_to_upstream(monkeypatch):
    import asyncio
    pa = _mk(Terminus2Patched, task_contract=True, contract_conditional=True)
    async def boom(*a, **kw):
        raise RuntimeError("api down")
    monkeypatch.setattr(pa._llm, "call", boom)
    g = asyncio.run(pa._clarity_gate("x"))
    assert g["on"] is False and "api down" in g["error"]
