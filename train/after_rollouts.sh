#!/bin/bash
# 第二轮采样结束后自动：导出 SFT 数据 → 传到 Pod → 停 vLLM（Seed / gpt 检验走外部接口，不受影响）→ 3 步测速。
# 测速结果由人看过再正式训练（显存、每步秒数）。
cd /root/work/agent_harness
POD="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -p ${POD_PORT:?set POD_PORT} root@${POD_HOST:?set POD_HOST}"
until [ -f /root/work/jobs/qroll-h2-synth-train-hint.done ]; do sleep 30; done
echo "$(TZ=America/New_York date +%H:%M) round 2 done"
bash train/export_sft.sh
for f in sft_plain.jsonl sft_all.jsonl; do $POD "mkdir -p /workspace/data && cat > /workspace/data/$f" < /root/work/train/$f; done
$POD 'wc -l /workspace/data/*.jsonl'
echo "$(TZ=America/New_York date +%H:%M) data on pod; stopping vLLM, speed test"
$POD 'pkill -f "[v]llm serve"; sleep 20; nvidia-smi --query-gpu=memory.used --format=csv,noheader; cd /workspace/code && /workspace/venv/bin/python sft_train.py --data /workspace/data/sft_all.jsonl --out /workspace/ckpt/speedtest --device-map cuda --drop-long --max-len 32768 --max-steps 3 --grad-accum 1 --thinking default > /workspace/logs/speedtest.log 2>&1; echo "speedtest rc=$?"; grep -vE "^\s*$" /workspace/logs/speedtest.log | grep -vE "Loading|it/s\]|s/it\]" | tail -15; nvidia-smi --query-gpu=memory.used --format=csv,noheader'
echo "$(TZ=America/New_York date +%H:%M) SPEEDTEST_DONE"
