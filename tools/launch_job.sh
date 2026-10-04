#!/bin/bash
# 启动一个（或几个同时的）Harbor job：tools/launch_job.sh <job 名> [<job 名> ...]（配置在 experiments/configs/<job>.resolved.yaml）
# 同一次调用里的多个 job 同时启动（D-040）。不加载 ~/.secrets.env：这些 job 只连我们自己的 vLLM（key 填 EMPTY），真 key 不进进程。
set -euo pipefail
cd /root/work/agent_harness
curl -sf -m 10 http://127.0.0.1:8000/v1/models > /tmp/models.json || { echo "vLLM not reachable at 127.0.0.1:8000"; exit 1; }
for J in "$@"; do
  m=$(grep -oE "model_name: openai/[a-z0-9]+" experiments/configs/$J.resolved.yaml | sed 's|.*/||')
  grep -q "\"$m\"" /tmp/models.json || { echo "$J needs model $m, not served"; exit 1; }
  ds=$(grep -oE "path: /root/work/train/[a-z_/]+" experiments/configs/$J.resolved.yaml | sed 's/path: //' || true)
  if [ -n "$ds" ] && [ -z "$(ls -A $ds 2>/dev/null)" ]; then echo "$J: dataset $ds missing or empty"; exit 1; fi
  [ -e /root/work/jobs/$J ] && { echo "/root/work/jobs/$J already exists; refusing to overwrite"; exit 1; }
  .venv/bin/harbor run -c experiments/configs/$J.resolved.yaml --dry-run > /dev/null 2>&1 || { echo "dry-run failed: $J"; exit 1; }
done
for J in "$@"; do
  tmux new-session -d -s $J "cd /root/work/agent_harness && export OPENAI_API_KEY=EMPTY PYTHONPATH=/root/work/agent_harness && .venv/bin/harbor run -c experiments/configs/$J.resolved.yaml -y > /root/work/jobs/$J.log 2>&1; touch /root/work/jobs/$J.done"
done
echo "launched at $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z'): $*"
