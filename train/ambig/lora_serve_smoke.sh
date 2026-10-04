#!/bin/bash
# 训练前检查：vLLM 能不能把 LoRA 适配器挂在 Qwen3-Coder-30B-A3B（MoE）上服务。只在没有实验在跑时执行（要重启 vLLM）。
# 适配器由 lora_smoke.py 生成（与 sft_train.py --targets attn 同格式）。结果写 /workspace/logs/lora_smoke_result.txt。
# 最后恢复成和四臂实验一模一样的服务（不带 LoRA），保证之后的 rollout 与实验用同一个服务配置。
set -uo pipefail
V=/workspace/venv; M=/workspace/models/Qwen3-Coder-30B-A3B-Instruct; export PATH=$V/bin:$PATH
R=/workspace/logs/lora_smoke_result.txt
: > $R
wait_up() { for i in $(seq 1 180); do curl -s localhost:8000/v1/models | grep -q "$1" && return 0; sleep 5; done; return 1; }
ask() {
  curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' \
    -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"Write a bash one-liner that counts .py files under the current directory.\"}],\"max_tokens\":60,\"temperature\":0}" \
    | python -c 'import json,sys; d=json.load(sys.stdin); print(d.get("model"), "->", repr(d["choices"][0]["message"]["content"][:150]))' >> $R 2>&1 \
    || echo "$1 -> REQUEST FAILED" >> $R
}
echo "[$(date -u +%H:%M:%S)] restart with LoRA" >> $R
pkill -f "[v]llm serve"; sleep 15
nohup vllm serve $M --served-model-name coder30b --port 8000 --host 127.0.0.1 --max-model-len 131072 --gpu-memory-utilization 0.92 \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder \
    --enable-lora --max-lora-rank 16 --max-loras 2 --lora-modules tiny=/workspace/ckpt/tiny_lora > /workspace/logs/vllm_lora.log 2>&1 &
if wait_up tiny; then
  ask coder30b; ask tiny
  echo "LORA_SERVE_OK" >> $R
else
  echo "LORA_SERVE_FAILED (see /workspace/logs/vllm_lora.log)" >> $R
  grep -iE "error|exception|not supported" /workspace/logs/vllm_lora.log | tail -8 >> $R
fi
echo "[$(date -u +%H:%M:%S)] restore plain server" >> $R
pkill -f "[v]llm serve"; sleep 15
nohup vllm serve $M --served-model-name coder30b --port 8000 --host 127.0.0.1 --max-model-len 131072 --gpu-memory-utilization 0.92 \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder > /workspace/logs/vllm.log 2>&1 &
wait_up coder30b && echo "PLAIN_SERVER_BACK" >> $R || echo "PLAIN_SERVER_FAILED" >> $R
echo "[$(date -u +%H:%M:%S)] done" >> $R
