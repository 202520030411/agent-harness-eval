#!/bin/bash
# D-057：第一批（qarm-*）四臂都结束后自动启动第二批（qarm2-*）；隧道暂时不通就每分钟重试，最多 20 次
cd /root/work/agent_harness
until [ "$(ls /root/work/jobs/qarm-*.done 2>/dev/null | wc -l)" -eq 4 ]; do sleep 30; done
echo "$(TZ=America/New_York date '+%H:%M') batch 1 done"
for i in $(seq 1 20); do
  bash tools/launch_qarms.sh qarm2 && exit 0
  echo "$(TZ=America/New_York date '+%H:%M') launch attempt $i failed; retry in 60s"; sleep 60
done
echo "GAVE UP launching batch 2"
