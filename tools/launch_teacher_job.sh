#!/bin/bash
# 启动带实时 Teacher 提示的 job（D-069）：Teacher 的 key 放 TEACHER_API_KEY（取自 ~/.secrets.env 的 OPENAI_API_KEY），
# Student 连自己的 vLLM 用 OPENAI_API_KEY=EMPTY。key 只在宿主机进程里，不进容器（D-051）。用法：tools/launch_teacher_job.sh <job>
set -euo pipefail
J=${1:?job}
cd /root/work/agent_harness
curl -sf -m 10 http://127.0.0.1:8000/v1/models | grep -q '"coder30b"' || { echo "vLLM not reachable"; exit 1; }
[ -e /root/work/jobs/$J ] && { echo "/root/work/jobs/$J exists"; exit 1; }
.venv/bin/harbor run -c experiments/configs/$J.resolved.yaml --dry-run > /dev/null 2>&1 || { echo "dry-run failed: $J"; exit 1; }
tmux new-session -d -s $J "cd /root/work/agent_harness && source ~/.secrets.env && export TEACHER_API_KEY=\$OPENAI_API_KEY && export OPENAI_API_KEY=EMPTY PYTHONPATH=/root/work/agent_harness && unset ANTHROPIC_API_KEY ARK_API_KEY OPENROUTER_API_KEY; .venv/bin/harbor run -c experiments/configs/$J.resolved.yaml -y > /root/work/jobs/$J.log 2>&1; touch /root/work/jobs/$J.done"
echo "launched at $(TZ=America/New_York date '+%H:%M %Z'): $J"
