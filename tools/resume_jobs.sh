#!/bin/bash
# 补跑：tools/resume_jobs.sh <job> [<job> ...] —— 删掉因 RuntimeError（基础设施，如 Docker 网络用尽）或 CancelledError（被手动中止）失败的 trial 后接着跑，
# 正常的失败（超时、没做对）不动。多个 job 同时启动。与 launch_job.sh 一样不加载任何真 key。
set -euo pipefail
cd /root/work/agent_harness
curl -sf -m 10 http://127.0.0.1:8000/v1/models | grep -q coder30b || { echo "vLLM not reachable"; exit 1; }
for J in "$@"; do
  [ -d /root/work/jobs/$J ] || { echo "no job dir $J"; exit 1; }
  rm -f /root/work/jobs/$J.done
  tmux new-session -d -s $J "cd /root/work/agent_harness && export OPENAI_API_KEY=EMPTY PYTHONPATH=/root/work/agent_harness && .venv/bin/harbor jobs resume -p /root/work/jobs/$J -f RuntimeError -f CancelledError > /root/work/jobs/$J.resume.log 2>&1; touch /root/work/jobs/$J.done"
done
echo "resumed at $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z'): $*"
