#!/bin/bash
# 第二批（qarm2-*）四臂都结束后：①Pod 上跑 LoRA 服务检查（要重启 vLLM；此时没有实验在跑）②生成两批合并报告
# ③只有 /root/work/AUTO_STOP_OK 存在（用户同意）才让 Pod 停机（Stop 后 GPU 不计费；实验数据都在 Hetzner）
POD="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -p ${POD_PORT:?set POD_PORT} root@${POD_HOST:?set POD_HOST}"
until [ "$(ls /root/work/jobs/qarm2-*.done 2>/dev/null | wc -l)" -eq 4 ]; do sleep 60; done
echo "$(TZ=America/New_York date '+%H:%M') batch 2 done"
cd /root/work/agent_harness && PYTHONPATH=. .venv/bin/python tools/qarm_report.py --prefixes qarm,qarm2 --out /root/work/reports/qarm > /root/work/reports/qarm_report.log 2>&1
echo "$(TZ=America/New_York date '+%H:%M') report written"
for i in 1 2 3; do $POD 'bash /workspace/code/lora_serve_smoke.sh' && break; sleep 30; done
$POD 'cat /workspace/logs/lora_smoke_result.txt' > /root/work/lora_smoke_result.txt 2>&1
echo "$(TZ=America/New_York date '+%H:%M') lora check: $(grep -E 'LORA_SERVE_(OK|FAILED)|PLAIN_SERVER' /root/work/lora_smoke_result.txt | tr '\n' ' ')"
if [ -f /root/work/AUTO_STOP_OK ]; then
  $POD 'eval "$(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(API_KEY|POD_ID)=" | sed "s/^/export /")"; runpodctl config --apiKey "$RUNPOD_API_KEY" >/dev/null 2>&1; runpodctl stop pod "$RUNPOD_POD_ID"' > /root/work/pod_stop.log 2>&1
  echo "$(TZ=America/New_York date '+%H:%M') pod stop requested: $(tail -1 /root/work/pod_stop.log)"
else
  echo "$(TZ=America/New_York date '+%H:%M') AUTO_STOP_OK not set; pod keeps running"
fi
