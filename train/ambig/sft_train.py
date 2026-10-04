"""LoRA SFT：只对 assistant 轮算 loss（逐轮用 chat template 前缀差分出 assistant 的 token）。

在 GPU 机器上：
  pip install "transformers>=4.51" peft accelerate datasets
  python sft_train.py --model /workspace/models/Qwen3-Coder-30B-A3B-Instruct --data sft.jsonl --out /workspace/ckpt/coder30b-ambig \
      --epochs 2 --targets attn --thinking default
然后合并或直接用 vLLM 的 LoRA 服务：
  vllm serve /workspace/models/Qwen3-Coder-30B-A3B-Instruct --served-model-name coder30b --enable-lora \
      --lora-modules ambig=/workspace/ckpt/coder30b-ambig --max-lora-rank 32 --port 8000
"""
from __future__ import annotations

import argparse
import json

import torch
from peft import LoraConfig, get_peft_model
from transformers import (AutoModelForCausalLM, AutoTokenizer, DataCollatorForSeq2Seq, Trainer, TrainingArguments)


def _ids(x):
    """transformers 5.x 的 apply_chat_template(tokenize=True) 返回 BatchEncoding（带 input_ids 的字典），4.x 返回 list；统一成 list。"""
    return list(x["input_ids"]) if hasattr(x, "keys") else list(x)


def build_example(tok, messages, max_len, enable_thinking):
    kw = {"enable_thinking": enable_thinking} if enable_thinking is not None else {}
    ids, labels = [], []
    prev = []
    for i, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        prefix = _ids(tok.apply_chat_template(messages[:i], tokenize=True, add_generation_prompt=True, **kw))
        full = _ids(tok.apply_chat_template(messages[:i + 1], tokenize=True, add_generation_prompt=False, **kw))
        assert full[:len(prefix)] == prefix, "chat template is not prefix-stable; cannot mask by prefix"
        # 追加：上一段结束到 prefix 结束之间是 system/user（不算 loss），prefix 之后到 full 结束是 assistant（算 loss）
        ids += prefix[len(prev):]; labels += [-100] * (len(prefix) - len(prev))
        ids += full[len(prefix):]
        labels += [-100] * (len(full) - len(prefix)) if m.get("train") is False else full[len(prefix):]   # train=False：留在上下文、不算 loss
        prev = full
    if max_len:   # 截断只在旧用法里用；Terminus 轨迹用 --drop-long（结尾的检查与交卷最重要，不能截掉）
        ids, labels = ids[:max_len], labels[:max_len]
    return {"input_ids": ids, "attention_mask": [1] * len(ids), "labels": labels}


def main(a):
    tok = AutoTokenizer.from_pretrained(a.model)
    rows = [json.loads(l) for l in open(a.data) if l.strip()]
    think = None if a.thinking == "default" else (a.thinking == "on")
    data = [build_example(tok, r["messages"], None if a.drop_long else a.max_len, think) for r in rows]
    if a.drop_long:
        lens = sorted(len(d["input_ids"]) for d in data)
        kept = [d for d in data if len(d["input_ids"]) <= a.max_len]
        print(f"drop-long: {len(data) - len(kept)} of {len(data)} examples longer than {a.max_len} tokens dropped "
              f"(median len {lens[len(lens) // 2]}, max {lens[-1]})")
        data = kept
    n_tok = sum(sum(1 for x in d["labels"] if x != -100) for d in data)
    print(f"{len(data)} examples, {n_tok} supervised tokens, max len {max(len(d['input_ids']) for d in data)}")

    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.bfloat16, attn_implementation="sdpa",
                                                 device_map=a.device_map)
    if getattr(model.config, "output_router_logits", False):   # MoE 负载均衡辅助 loss：只训注意力层时关掉
        model.config.output_router_logits = False
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    targets = ["q_proj", "k_proj", "v_proj", "o_proj"] + (["gate_proj", "up_proj", "down_proj"] if a.targets == "all" else [])
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules=targets))
    model.print_trainable_parameters()

    # transformers 5.x 去掉了 warmup_ratio，改成 warmup_steps 接受 < 1 的小数（按比例）；两种版本都按前 5% 步数预热
    import inspect
    warm = ({"warmup_ratio": 0.05} if "warmup_ratio" in inspect.signature(TrainingArguments.__init__).parameters
            else {"warmup_steps": 0.05})
    args = TrainingArguments(output_dir=a.out, num_train_epochs=a.epochs, per_device_train_batch_size=1,
                             gradient_accumulation_steps=a.grad_accum, learning_rate=a.lr, lr_scheduler_type="cosine",
                             **warm, logging_steps=5, save_strategy="epoch", bf16=True, report_to=[],
                             remove_unused_columns=False, max_steps=a.max_steps)
    trainer = Trainer(model=model, args=args, train_dataset=data,
                      data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100))
    trainer.train()
    model.save_pretrained(a.out); tok.save_pretrained(a.out)
    print("saved", a.out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="/workspace/models/Qwen3-Coder-30B-A3B-Instruct")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=8192)
    ap.add_argument("--targets", choices=["attn", "all"], default="attn",
                    help="MoE 模型（如 Qwen3-Coder-30B-A3B）只能用 attn：给每个专家的前馈层挂 LoRA 会爆显存，vLLM 也不支持")
    ap.add_argument("--device-map", default=None, help="单卡放不下时用 auto 跨卡切分；单卡 H200 用 cuda 直接载到显存")
    ap.add_argument("--drop-long", action="store_true", help="超过 --max-len 的样本整条丢掉而不是截断")
    ap.add_argument("--max-steps", type=int, default=-1, help=">0 时只跑这么多步（测速度 / 显存）")
    ap.add_argument("--thinking", choices=["on", "off", "default"], default="off",
                    help="Qwen3：训练与推理要一致；默认关闭思考，动作就是一个 JSON")
    main(ap.parse_args())
