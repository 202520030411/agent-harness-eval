#!/bin/bash
# 只挂原版（不开 LoRA），参数与 gpu_bootstrap.sh 第 3 步相同——D-069 的 Teacher 轮和前几轮采样都是这个配置，D-074 试点重跑要与之一致。
# 用法（Pod）：bash serve_plain.sh   → 最后一行 SERVE_PLAIN_OK 或 SERVE_PLAIN_FAILED
# pkill 必须写在脚本文件里执行：若和 "vllm serve …" 写在同一条 ssh 命令里，"[v]llm serve" 会匹配到那条命令自己的 shell，把它杀掉（2026-09-27 22:09 事故）。
set -uo pipefail
V=/workspace/venv; M=/workspace/models/Qwen3-Coder-30B-A3B-Instruct; export PATH=$V/bin:$PATH
pkill -f "[v]llm serve"; sleep 15
nohup vllm serve $M --served-model-name coder30b --port 8000 --host 127.0.0.1 --max-model-len 131072 --gpu-memory-utilization 0.92 \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder > /workspace/logs/vllm.log 2>&1 &
for i in $(seq 1 180); do curl -s localhost:8000/v1/models | grep -q '"coder30b"' && break; sleep 5; done
curl -s localhost:8000/v1/models | grep -q '"coder30b"' && echo SERVE_PLAIN_OK || echo SERVE_PLAIN_FAILED
