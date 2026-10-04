#!/bin/bash
# RL（D-072）：vLLM 挂原版 coder30b + 当前策略的适配器（名字 policyNN，每步一个新名字，名字本身就证明挂的是哪一步）。
# vLLM 参数与 serve_lora.sh 完全相同（同一套服务配置，RL 与 SFT 的结果才可比）。
# 用法（Pod）：bash serve_policy.sh policy03 /workspace/rl/policy03   → 最后一行 SERVE_POLICY_OK 或 SERVE_POLICY_FAILED
set -uo pipefail
V=/workspace/venv; M=/workspace/models/Qwen3-Coder-30B-A3B-Instruct; export PATH=$V/bin:$PATH
name=${1:?name}; path=${2:?adapter dir}
[ -f "$path/adapter_model.safetensors" ] || { echo "SERVE_POLICY_FAILED: no adapter at $path"; exit 1; }
pkill -f "[v]llm serve"; sleep 15
nohup vllm serve $M --served-model-name coder30b --port 8000 --host 127.0.0.1 --max-model-len 131072 --gpu-memory-utilization 0.92 \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder \
    --enable-lora --max-lora-rank 16 --max-loras 1 --lora-modules "$name=$path" > /workspace/logs/vllm.log 2>&1 &
for i in $(seq 1 180); do curl -s localhost:8000/v1/models | grep -q "\"$name\"" && break; sleep 5; done
curl -s localhost:8000/v1/models | grep -q "\"$name\"" && echo "SERVE_POLICY_OK $name" || echo "SERVE_POLICY_FAILED $name"
