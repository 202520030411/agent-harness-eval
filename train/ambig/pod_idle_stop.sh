#!/bin/bash
# pod 空闲自停（D-091）：vLLM 连续 IDLE_MIN 分钟没有正在跑、也没有排队的请求，就把这台 pod 停掉（停止，不是删除；/workspace 保留）。
# 起因：跑完之后没人停 pod，GPU 空转（D-087，一夜约 $39）。我（Claude）登不上 pod，也不能保证按时被叫醒，所以让 pod 自己停。
# 用法（在 pod 上）：nohup bash /workspace/pod_idle_stop.sh > /dev/null 2>&1 &     日志：/workspace/logs/idle_stop.log
# 先试：DRY_RUN=1 bash /workspace/pod_idle_stop.sh   （只检查能不能读到 vLLM 指标和停机命令，不停机）
IDLE_MIN=${IDLE_MIN:-30}
LOG=/workspace/logs/idle_stop.log
mkdir -p /workspace/logs
# ssh 会话里通常没有 RunPod 注入的环境变量；从 1 号进程读（RUNPOD_POD_ID、RUNPOD_API_KEY）
eval "$(tr '\0' '\n' < /proc/1/environ | grep -E '^RUNPOD_(POD_ID|API_KEY)=' | sed 's/^/export /')"

stop_pod() {
  if command -v runpodctl >/dev/null 2>&1 && [ -n "$RUNPOD_POD_ID" ]; then
    runpodctl stop pod "$RUNPOD_POD_ID" >> "$LOG" 2>&1
  else
    echo "$(date -u +%FT%TZ) cannot stop: runpodctl or RUNPOD_POD_ID missing" >> "$LOG"
  fi
}

metric() {   # 某个 vLLM 指标的总和（可能有多个标签行）；读不到返回空
  echo "$1" | awk -v k="$2" 'index($1, k "{") == 1 || $1 == k {s += $NF; n++} END {if (n) printf "%d", s}'
}

if [ -n "$DRY_RUN" ]; then
  m=$(curl -s -m 10 http://127.0.0.1:8000/metrics)
  echo "pod id: ${RUNPOD_POD_ID:-MISSING}; runpodctl: $(command -v runpodctl || echo MISSING); api key: $([ -n "$RUNPOD_API_KEY" ] && echo present || echo MISSING)"
  echo "vllm running=$(metric "$m" vllm:num_requests_running) waiting=$(metric "$m" vllm:num_requests_waiting)"
  exit 0
fi

idle=0; seen_up=0; boot_min=0
BOOT_MAX_MIN=${BOOT_MAX_MIN:-90}    # 开机后这么久 vLLM 都没起来 → 按开机失败停机
while true; do
  m=$(curl -s -m 10 http://127.0.0.1:8000/metrics)
  run=$(metric "$m" vllm:num_requests_running); wait_=$(metric "$m" vllm:num_requests_waiting)
  done_n=$(metric "$m" vllm:request_success_total)
  # 处理过第一个请求才算"开始干活"；在那之前（开机、等人启动任务）最多宽限 BOOT_MAX_MIN 分钟（D-095：两台 pod 在等启动时被停）
  if [ -n "$done_n" ] && [ "$done_n" -gt 1 ]; then seen_up=1; fi
  if [ "$seen_up" = "0" ]; then
    # 还在开机（下载模型、加载）：不算空闲（D-095：之前把这段也算成空闲，可能在开机途中把 pod 停了）
    boot_min=$((boot_min + 1))
    echo "$(date -u +%FT%TZ) waiting for vLLM and the first real requests (boot_min=$boot_min, served=${done_n:-NA})" >> "$LOG"
    if [ "$boot_min" -ge "$BOOT_MAX_MIN" ]; then
      echo "$(date -u +%FT%TZ) no real work within $BOOT_MAX_MIN minutes of boot: stopping pod $RUNPOD_POD_ID" >> "$LOG"
      stop_pod; exit 0
    fi
    sleep 60; continue
  fi
  # vLLM 起来过之后：没有请求、或者读不到（挂了）都算空闲——这时 GPU 同样在白烧
  if [ "${run:-0}" = "0" ] && [ "${wait_:-0}" = "0" ]; then idle=$((idle + 1)); else idle=0; fi
  echo "$(date -u +%FT%TZ) running=${run:-NA} waiting=${wait_:-NA} idle_min=$idle" >> "$LOG"
  if [ "$idle" -ge "$IDLE_MIN" ]; then
    echo "$(date -u +%FT%TZ) idle for $IDLE_MIN minutes: stopping pod $RUNPOD_POD_ID" >> "$LOG"
    stop_pod
    exit 0
  fi
  sleep 60
done
