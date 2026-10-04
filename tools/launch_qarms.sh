#!/bin/bash
# Qwen 四臂同时启动（D-040）：tools/launch_qarms.sh qsmoke | qarm
# 不加载 ~/.secrets.env：这几个臂只连我们自己的 vLLM（key 填 EMPTY，vLLM 不校验），真 key 不进这些进程，也不进容器（D-051）。
set -euo pipefail
P=${1:?usage: launch_qarms.sh qsmoke|qarm}
ARMS="h0-baseline h1-interface h2-gate h3-qwencode"
cd /root/work/agent_harness
# 两条隧道：127.0.0.1:8000 给 Terminus（主循环在主机上），172.17.0.1:8000 给 qwen-code（跑在题目容器里）
for u in http://127.0.0.1:8000/v1/models http://172.17.0.1:8000/v1/models; do
  curl -sf -m 10 "$u" | grep -q coder30b || { echo "vLLM not reachable at $u"; exit 1; }
done
for a in $ARMS; do
  J=$P-$a
  [ -e /root/work/jobs/$J ] && { echo "/root/work/jobs/$J already exists; refusing to overwrite"; exit 1; }
  .venv/bin/harbor run -c experiments/configs/$J.resolved.yaml --dry-run > /dev/null 2>&1 || { echo "dry-run failed: $J"; exit 1; }
done
for a in $ARMS; do
  J=$P-$a
  tmux new-session -d -s $J "cd /root/work/agent_harness && export OPENAI_API_KEY=EMPTY PYTHONPATH=/root/work/agent_harness && .venv/bin/harbor run -c experiments/configs/$J.resolved.yaml -y > /root/work/jobs/$J.log 2>&1; touch /root/work/jobs/$J.done"
done
echo "launched at $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z'):"; tmux ls | grep "^$P-"
