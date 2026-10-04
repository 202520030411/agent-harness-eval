#!/bin/bash
# D-072 试点（用户 2026-09-27 “做你的实验”）：gpt-6-sol 读失败记录写 PSP 式开头规则（API 约 5 美元，超过 8 美元自动停）→
# 等评测把原版挂上（评测期间 GPU 本来就在跑，不额外花 GPU 钱）→ 原版带规则做同 51 道难题 × 2 → 出对比报告。
cd /root/work/agent_harness
T=/root/work/train
say() { echo "$(TZ=America/New_York date +%H:%M) $*"; }
( set -a; . ~/.secrets.env; set +a
  PYTHONPATH=. .venv/bin/python train/synth/psp_rules.py --tasks-dir $T/synth_split/train_hard --knowledge $T/teacher_knowledge.json \
      --jobs /root/work/jobs/qroll-h2-synth-train /root/work/jobs/qroll-h2-synth-train-hint \
      --dst $T/synth_split/train_psp --hints-out $T/hints_psp.json --rules-out $T/psp_rules.json ) || { say "RULES_FAILED"; exit 1; }
# 每道题都要读到失败记录、都要有规则，否则就不是“读过失败再写规则”，停下不跑
python3 -c "import json,sys; r=json.load(open('$T/psp_rules.json')); bad=[x['task'] for x in r if x['n_failed_seen'] < 1 or not x['rules']]; print('tasks without failures or rules:', bad); sys.exit(1 if bad else 0)" \
  || { say "RULES_INCOMPLETE — not launching"; exit 1; }
say "rules written; waiting for the eval to bring up the base model"
until grep -qE "EVAL_LAUNCHED|ADAPTER_CHECK_FAILED" $T/after_keep_eval.log 2>/dev/null; do sleep 60; done
bash tools/launch_job.sh qpilot-psp-rules || { say "PILOT_LAUNCH_FAILED"; exit 1; }
until [ -f /root/work/jobs/qpilot-psp-rules.done ]; do sleep 60; done
PYTHONPATH=. .venv/bin/python tools/psp_pilot_report.py --out /root/work/reports/psp_pilot
say "PILOT_DONE"
