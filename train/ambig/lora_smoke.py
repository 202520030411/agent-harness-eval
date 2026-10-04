"""训练前的迷你检查：造一个和 sft_train.py（--targets attn，r=16，alpha=32）同格式的随机 LoRA 适配器，
用来确认 vLLM 能把它挂在 Qwen3-Coder-30B-A3B（MoE）上服务。只用 CPU、不加载模型权重（结构建在 meta 设备上，只把 LoRA 参数落到 CPU）。
用法（Pod）：/workspace/venv/bin/python lora_smoke.py --model /workspace/models/Qwen3-Coder-30B-A3B-Instruct --out /workspace/ckpt/tiny_lora
"""
from __future__ import annotations

import argparse

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoConfig, AutoModelForCausalLM


def main(a):
    cfg = AutoConfig.from_pretrained(a.model)
    with torch.device("meta"):
        model = AutoModelForCausalLM.from_config(cfg, torch_dtype=torch.bfloat16)
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    n = 0
    for mod in model.modules():
        if hasattr(mod, "lora_A") and "default" in getattr(mod, "lora_A", {}):
            for sub in (mod.lora_A["default"], mod.lora_B["default"]):
                sub.to_empty(device="cpu")
                torch.nn.init.normal_(sub.weight, std=0.01)
                n += sub.weight.numel()
    model.save_pretrained(a.out)
    print(f"saved {a.out}: {n / 1e6:.1f}M LoRA params")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rank", type=int, default=16)
    main(ap.parse_args())
