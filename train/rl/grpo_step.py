"""PSP 式 GRPO 的一次参数更新（D-072；在 Pod 上跑，先停掉 vLLM 腾出显存）。
输入 batch.jsonl：每行 {messages, advantage}（grpo_loop.py 用 grpo.trial_example 生成，只含 advantage ≠ 0 的 trial）。
  loss = −Σ_i A_i · Σ_t log π(y_it) / Σ_i T_i
只有 Qwen 自己的回复算（掩码同 SFT 的 build_example：开场 / 观察 / 提示 / train=False 的轮都不算）；按 token 总数归一（DAPO 的做法，长短轨迹一视同仁）。
每步只更新一次、样本都来自当前策略 → 重要性比值恒为 1，不需要 PPO 的裁剪；不加 KL 项（LoRA + 20 步，漂移有限；由 grpo_loop 的止损规则兜底）。
LoRA 同 SFT（只训注意力层 q/k/v/o，r16、α32），dropout 为 0（训练时的策略要和 vLLM 采样时完全一致）；Adam 状态存在适配器目录里，下一步接着用。
用法（Pod）：
  python grpo_step.py --init-only --adapter-out /workspace/rl/policy00                                     # 第 0 步：B=0 的适配器，与原版等价
  python grpo_step.py --batch /workspace/rl/step01/batch.jsonl --adapter-in /workspace/rl/policy00 --adapter-out /workspace/rl/policy01
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))                    # Pod 上与 sft_train.py 同在 /workspace/code
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ambig"))      # 仓库里 sft_train.py 在 train/ambig/

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj"]


def load_batch(tok, path: str, max_len: int) -> tuple[list[tuple], dict]:
    """batch.jsonl → [(样本, advantage, 算 loss 的 token 数, 去掉提示的同一样本或 None)]；超长或没有可训 token 的丢掉并计数。"""
    from sft_train import build_example
    kept, why = [], {"too_long": 0, "no_trainable_tokens": 0}
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        try:   # 一条轨迹的模板出错（如回复以换行开头 → 前缀不稳定的 assert）只丢这一条，不让整步崩、重跑时再崩
            ex = build_example(tok, r["messages"], None, None)
        except Exception as e:  # noqa: BLE001
            why["template_error"] = why.get("template_error", 0) + 1
            print(f"skip row ({r.get('task')}): {type(e).__name__}: {e}", file=sys.stderr)
            continue
        n = sum(1 for x in ex["labels"] if x != -100)
        if len(ex["input_ids"]) > max_len:
            why["too_long"] += 1
        elif n == 0:
            why["no_trainable_tokens"] += 1
        else:
            try:
                ex0 = build_example(tok, r["messages_nohint"], None, None) if r.get("messages_nohint") else None
            except Exception:  # noqa: BLE001  只影响提示依赖度这个记录项
                ex0 = None
            kept.append((ex, float(r["advantage"]), n, ex0))
    return kept, why


IDENTITY = {"temperature": 1.0, "top_k": 0, "top_p": 1.0, "repetition_penalty": 1.0}


def sampler_settings(model_dir: str) -> dict:
    """vLLM 真正的采样分布：请求里不带采样参数（D-026），vLLM 就用模型目录里 generation_config.json 的默认值
    （Qwen3-Coder：temperature 0.7、top_k 20、top_p 0.8、repetition_penalty 1.05，QWEN_PLAN §2）。文件不存在时 vLLM 也不改分布 → 恒等。"""
    f = Path(model_dir) / "generation_config.json"
    g = json.load(open(f)) if f.exists() else {}
    return {"temperature": float(g.get("temperature") or 1.0), "top_k": int(g.get("top_k") or 0),
            "top_p": float(g.get("top_p") or 1.0), "repetition_penalty": float(g.get("repetition_penalty") or 1.0)}


def token_logprobs(z, tgt, pos, first_seen, s: dict):
    """每个目标 token 在 vLLM 采样分布下的 log-prob。顺序同 vLLM 的采样器：重复惩罚 → 除以温度 → top-k → 在 top-k 里按 top-p 截断再归一。
    z [n, V] fp32 logits；tgt [n]；pos [n] = 该位置能看到的最后一个 token 的下标；first_seen [V] = 每个 token 第一次出现的位置。
    返回 (log-prob [n], 落在截断集合外的个数)；落在外面的（bf16 数值差异）退回不截断的 log-softmax。"""
    import torch
    if s["repetition_penalty"] != 1.0:        # 上下文里出现过的 token：正 logit 除以惩罚、负 logit 乘以惩罚（vLLM apply_penalties）
        seen = first_seen[None, :] <= pos[:, None]
        z = torch.where(seen, torch.where(z > 0, z / s["repetition_penalty"], z * s["repetition_penalty"]), z)
    if s["temperature"] != 1.0:
        z = z / s["temperature"]
    zy = z.gather(-1, tgt[:, None]).squeeze(-1)
    full = z.logsumexp(-1)
    if s["top_k"] <= 0 and s["top_p"] >= 1.0:
        return zy - full, torch.zeros((), dtype=torch.long, device=z.device)
    k = s["top_k"] if 0 < s["top_k"] < z.shape[-1] else z.shape[-1]
    v, vi = z.topk(k, dim=-1)                                   # 从大到小
    q = v.softmax(-1)
    keep = (q.cumsum(-1) - q) < s["top_p"]                     # 排在它前面的概率和已达到 top_p 的丢掉；第一个总保留（同 vLLM）
    lse = v.masked_fill(~keep, float("-inf")).logsumexp(-1)
    inside = ((vi == tgt[:, None]) & keep).any(-1)
    return torch.where(inside, zy - lse, zy - full), (~inside).sum()


def nll_sum(model, ids, labels, chunk: int = 2048, sampler: dict | None = None, counts: dict | None = None):
    """这条轨迹上可训 token 的 NLL 之和（在 vLLM 实际采样的分布下，见 token_logprobs；sampler=None 即原始 softmax）。
    只在这些位置算词表上的 logits，分块算、反向时重算：整条 64k token 的全词表 logits（fp32 约 39 GB）不会一次放进显存。"""
    import torch
    from torch.utils.checkpoint import checkpoint
    s = sampler or IDENTITY
    base = model.get_base_model()
    h = base.model(input_ids=ids, use_cache=False).last_hidden_state[0, :-1]      # 第 i 个位置预测第 i+1 个 token
    tgt = labels[0, 1:]
    idx = (tgt != -100).nonzero().squeeze(-1)
    h, tgt = h[idx], tgt[idx]
    first = None
    if s["repetition_penalty"] != 1.0:
        L, V = ids.shape[1], base.lm_head.weight.shape[0]
        first = torch.full((V,), L, dtype=torch.long, device=ids.device)
        first.scatter_reduce_(0, ids[0], torch.arange(L, device=ids.device), reduce="amin")

    def ce(hs, ts, ps):
        lp, n_out = token_logprobs(base.lm_head(hs).float(), ts, ps, first, s)
        return -lp.sum(), n_out
    parts = [checkpoint(ce, h[i:i + chunk], tgt[i:i + chunk], idx[i:i + chunk], use_reentrant=False) for i in range(0, len(idx), chunk)]
    if counts is not None:
        counts["scored"] = counts.get("scored", 0) + len(idx)
        counts["outside_nucleus"] = counts.get("outside_nucleus", 0) + sum(int(n) for _, n in parts)
    return sum(x for x, _ in parts)


def step_on_batch(model, batch: list[tuple], opt, params, clip: float, device: str, sampler: dict | None = None) -> dict:
    """一次更新：逐条前向 + 反向累积梯度（每条 loss = A · NLL 之和 / ΣT，合起来就是 −Σ A·Σ log π / ΣT），再走一步优化器。"""
    import torch
    model.train()
    n_tok = sum(item[2] for item in batch)
    obj, nll_pos, nll_neg, reliance, counts = 0.0, [], [], [], {}
    for item in batch:
        ex, adv, n = item[:3]
        ex0 = item[3] if len(item) > 3 else None
        ids = torch.tensor([ex["input_ids"]], device=device)
        labels = torch.tensor([ex["labels"]], device=device)
        s = nll_sum(model, ids, labels, sampler=sampler, counts=counts)
        loss = adv * s / n_tok
        loss.backward()
        obj += loss.item()
        (nll_pos if adv > 0 else nll_neg).append(s.item() / n)
        if ex0 is not None:
            # 提示依赖度（HiLL）：同一条做对的轨迹，带提示与不带提示时每个 token 平均 log-prob 之差；参数还没更新，只前向、不求梯度
            n0 = sum(1 for x in ex0["labels"] if x != -100)
            if n0:
                with torch.no_grad():
                    s0 = nll_sum(model, torch.tensor([ex0["input_ids"]], device=device), torch.tensor([ex0["labels"]], device=device),
                                 sampler=sampler)
                reliance.append(s0.item() / n0 - s.item() / n)
    grad_norm = float(torch.nn.utils.clip_grad_norm_(params, clip))
    opt.step()
    opt.zero_grad(set_to_none=True)
    mean = lambda xs: sum(xs) / len(xs) if xs else None   # noqa: E731
    # LoRA 的 B 矩阵初始为 0（与原版等价）；更新后它的范数 > 0 说明权重真的变了（冒烟测试看这个数）
    b_norm = float(sum(p.detach().float().pow(2).sum() for n, p in model.named_parameters() if "lora_B" in n) ** 0.5)
    rs = sorted(reliance)
    return {"examples": len(batch), "trainable_tokens": n_tok, "objective": obj, "grad_norm_before_clip": grad_norm,
            "mean_nll_pos_adv": mean(nll_pos), "mean_nll_neg_adv": mean(nll_neg), "lora_b_norm": b_norm,
            "hint_reliance": {"n": len(rs), "mean": mean(rs), "median": rs[len(rs) // 2] if rs else None},
            "sampler": sampler or IDENTITY, "outside_nucleus_frac": counts.get("outside_nucleus", 0) / max(1, counts.get("scored", 0)),
            # 按 advantage 正负看这一批实际学了什么（超长 / 摘要丢掉的多半是长的失败轨迹 → 看正负是否失衡）
            "n_pos": sum(1 for it in batch if it[1] > 0), "n_neg": sum(1 for it in batch if it[1] < 0),
            "tok_pos": sum(it[2] for it in batch if it[1] > 0), "tok_neg": sum(it[2] for it in batch if it[1] < 0),
            "adv_token_balance": sum(it[1] * it[2] for it in batch) / max(1, n_tok)}


def main(a) -> None:
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    t0 = time.time()
    torch.manual_seed(0)
    tok = AutoTokenizer.from_pretrained(a.model)
    batch, dropped = ([], {}) if a.init_only else load_batch(tok, a.batch, a.max_len)
    n_bad = dropped.get("template_error", 0)
    if n_bad > max(2, 0.05 * (len(batch) + sum(dropped.values()))):   # 个别一条是偶发；成批出错说明模板 / 分词器本身有问题 → 大声停
        raise SystemExit(f"systematic chat-template errors, not training on this batch: {dropped}")
    if not a.init_only and not batch:   # Pod 上全被丢掉（超长 / 模板出错）：策略不变、照常交出新名字的适配器（重跑同一批也不会反复崩）
        import shutil
        from safetensors.torch import load_file
        shutil.copytree(a.adapter_in, a.adapter_out, dirs_exist_ok=True)   # 连同 optimizer.pt
        w = load_file(str(Path(a.adapter_in) / "adapter_model.safetensors"))
        b = float(sum(v.float().pow(2).sum() for k, v in w.items() if "lora_B" in k) ** 0.5)
        print("GRPO_STEP_STATS " + json.dumps({"examples": 0, "trainable_tokens": 0, "lora_b_norm": b, "dropped": dropped, "lr": a.lr,
                                               "skipped": "every row dropped on the pod", "total_sec": round(time.time() - t0)}))
        return
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.bfloat16, attn_implementation="sdpa", device_map="cuda")
    if getattr(model.config, "output_router_logits", False):   # MoE 负载均衡辅助 loss：只训注意力层时关掉（同 SFT）
        model.config.output_router_logits = False
    if a.init_only:
        model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.0, task_type="CAUSAL_LM",
                                                 target_modules=TARGETS))
        model.save_pretrained(a.adapter_out); tok.save_pretrained(a.adapter_out)
        print("GRPO_INIT_OK " + a.adapter_out)
        return
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = PeftModel.from_pretrained(model, a.adapter_in, is_trainable=True)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, betas=(0.9, 0.999), weight_decay=0.0)
    sampler = IDENTITY if a.raw_softmax else sampler_settings(a.model)
    opt_state, tag = Path(a.adapter_in) / "optimizer.pt", Path(a.adapter_in) / "sampler.json"
    same = (json.load(open(tag)) if tag.exists() else IDENTITY) == sampler   # 没有标记 = 旧代码训的 = 原始 softmax
    if opt_state.exists() and same:
        opt.load_state_dict(torch.load(opt_state, map_location="cuda"))
        for g in opt.param_groups:          # load_state_dict 会把存档里的 lr 盖回来；以本次 --lr 为准
            g["lr"] = a.lr
    elif opt_state.exists():                # 存档的 Adam 动量是按另一种 log-prob 定义累积的：不接着用（D-079）
        print(f"fresh Adam state: saved one was built under a different log-prob definition (now {sampler})", flush=True)
    t_load = time.time() - t0

    stats = step_on_batch(model, batch, opt, params, a.clip, "cuda", sampler=sampler)
    Path(a.adapter_out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(a.adapter_out); tok.save_pretrained(a.adapter_out)
    torch.save(opt.state_dict(), Path(a.adapter_out) / "optimizer.pt")
    (Path(a.adapter_out) / "sampler.json").write_text(json.dumps(sampler))
    stats["peak_gpu_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 1)
    print("GRPO_STEP_STATS " + json.dumps({**stats, "dropped": dropped, "lr": a.lr, "load_sec": round(t_load),
                                           "total_sec": round(time.time() - t0)}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="/workspace/models/Qwen3-Coder-30B-A3B-Instruct")
    ap.add_argument("--batch")
    ap.add_argument("--adapter-in")
    ap.add_argument("--adapter-out", required=True)
    ap.add_argument("--init-only", action="store_true")
    ap.add_argument("--lr", type=float, default=5e-5, help="SFT 用 1e-4；RL 的梯度来自单次采样的 advantage，更吵，取一半")
    ap.add_argument("--clip", type=float, default=1.0)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=65536, help="SFT 是 32k；RL 要让长的失败轨迹也进训练（见 nll_sum）")
    ap.add_argument("--raw-softmax", action="store_true", help="按原始 softmax（温度 1、不截断）算 log-prob；默认按 vLLM 的采样分布算")
    main(ap.parse_args())
