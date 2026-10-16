#!/bin/bash
# 等 vLLM 通了就立刻启动（D-095）：pod 开好、线路接上之后不再等人转告，避免 pod 在空等中被自停脚本停掉。
# 用法（在 Hetzner 的 tmux 里）：bash tools/launch_when_ready.sh "<job1> <job2> ..." "<接续脚本的参数>"
# 只在用户已经同意这些 job 之后才启用。最多等 MAX_WAIT_MIN 分钟；日志 /root/work/chains/launcher.log（美东时间）。
set -u
JOBS="$1"; CHAIN_ARGS="$2"
MAX_WAIT_MIN=${MAX_WAIT_MIN:-240}
LOG=/root/work/chains/launcher.log
cd /root/work/agent_harness
log() { echo "[$(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')] $*" >> "$LOG"; }
log "armed: waiting for coder30b at 127.0.0.1:8000, then launching: $JOBS"
for i in $(seq 1 "$MAX_WAIT_MIN"); do
  if curl -sf -m 10 http://127.0.0.1:8000/v1/models | grep -q '"coder30b"'; then
    log "vLLM is up after $i minute(s)"
    if bash tools/launch_job.sh $JOBS >> "$LOG" 2>&1; then
      tmux new-session -d -s chain-auto "cd /root/work/agent_harness && PYTHONPATH=. .venv/bin/python tools/chain_round.py $CHAIN_ARGS >> /root/work/chains/chain-auto.log 2>&1"
      log "launched jobs and started the chain (tmux chain-auto): $CHAIN_ARGS"
    else
      log "launch_job.sh refused; nothing started"
    fi
    exit 0
  fi
  sleep 60
done
log "gave up: vLLM not reachable within $MAX_WAIT_MIN minutes; nothing started"
