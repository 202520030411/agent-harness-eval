"""The loss must score Qwen's tokens under the distribution vLLM samples from (rep. penalty -> temperature -> top-k -> top-p)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
torch = pytest.importorskip("torch")

S = {"temperature": 0.7, "top_k": 20, "top_p": 0.8, "repetition_penalty": 1.05}


def vllm_reference(z, seen, s):
    """Row-wise copy of vLLM's sampler: apply_penalties (repetition only) then temperature then apply_top_k_top_p (ascending sort)."""
    z = z.clone()
    rp = s["repetition_penalty"]
    z = torch.where(seen & (z > 0), z / rp, torch.where(seen & (z <= 0), z * rp, z))
    z = z / s["temperature"]
    zs, zi = z.sort(dim=-1, descending=False)
    thr = zs.gather(1, torch.full((z.shape[0], 1), z.shape[1] - s["top_k"]))
    zs = zs.masked_fill(zs < thr, float("-inf"))
    cs = zs.softmax(-1).cumsum(-1)
    m = cs <= 1 - s["top_p"]
    m[:, -1] = False
    zs = zs.masked_fill(m, float("-inf"))
    return zs.scatter(1, zi, zs).log_softmax(-1)


def test_scorer_matches_vllm_sampler_row_by_row():
    from train.rl.grpo_step import token_logprobs
    g = torch.Generator().manual_seed(0)
    n, V = 64, 300
    z = torch.randn(n, V, generator=g) * 4
    ids = torch.randint(0, V, (n + 1,), generator=g)
    first = torch.full((V,), n + 1, dtype=torch.long)
    first.scatter_reduce_(0, ids, torch.arange(n + 1), reduce="amin")
    pos = torch.arange(n)
    seen = first[None, :] <= pos[:, None]
    ref = vllm_reference(z, seen, S)
    tgt = ref.argmax(-1)                                    # always inside the kept set
    lp, n_out = token_logprobs(z, tgt, pos, first, S)
    assert int(n_out) == 0
    assert torch.allclose(lp, ref.gather(1, tgt[:, None]).squeeze(1), atol=1e-5)
    kept = torch.isfinite(ref)                               # sampled tokens can be any kept token, not only the argmax
    for i in range(n):
        for y in kept[i].nonzero().squeeze(-1).tolist():
            lpi, _ = token_logprobs(z[i:i + 1], torch.tensor([y]), pos[i:i + 1], first, S)
            assert abs(float(lpi) - float(ref[i, y])) < 1e-5


def test_identity_sampler_is_plain_cross_entropy_and_confident_tokens_get_no_gradient():
    from train.rl.grpo_step import IDENTITY, token_logprobs
    z = torch.tensor([[8.0, 1.0, 0.5, 0.0], [1.0, 0.9, 0.8, 0.7]], requires_grad=True)
    tgt = torch.tensor([0, 2])
    pos, first = torch.tensor([0, 1]), torch.full((4,), 9, dtype=torch.long)
    lp, _ = token_logprobs(z, tgt, pos, first, IDENTITY)
    assert torch.allclose(lp, torch.log_softmax(z, -1).gather(1, tgt[:, None]).squeeze(1), atol=1e-6)
    s = dict(S, top_k=3, repetition_penalty=1.0)
    lp, _ = token_logprobs(z, tgt, pos, first, s)
    lp[0].backward()
    assert float(lp[0]) == 0.0 and torch.all(z.grad[0] == 0)   # vLLM can only emit token 0 there: no choice, no gradient


def test_nll_sum_with_sampler_runs_through_checkpoint_and_backward():
    from peft import LoraConfig, get_peft_model
    from transformers import LlamaConfig, LlamaForCausalLM
    from train.rl.grpo_step import nll_sum
    torch.manual_seed(0)
    m = LlamaForCausalLM(LlamaConfig(vocab_size=40, hidden_size=32, intermediate_size=64, num_hidden_layers=2, num_attention_heads=2,
                                     num_key_value_heads=2, max_position_embeddings=64))
    m = get_peft_model(m, LoraConfig(r=4, lora_alpha=8, lora_dropout=0.0, target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    ids = list(range(3, 30))
    labels = [-100] * 5 + ids[5:12] + [-100] * 4 + ids[16:]
    counts = {}
    s = nll_sum(m, torch.tensor([ids]), torch.tensor([labels]), chunk=4, sampler=dict(S, top_k=10), counts=counts)
    s.backward()
    assert counts["scored"] == sum(1 for x in labels[1:] if x != -100)
    assert any(p.grad is not None for n, p in m.named_parameters() if "lora_A" in n)
