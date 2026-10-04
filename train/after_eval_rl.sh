#!/bin/bash
# D-072 已批准步骤的自动串联（中间不让 GPU 空等）：
#   等 9 组 SFT 评测结束 → SFT 报告 ─▶ 试点重跑（D-074，同 B 的条件）─(A)─▶ RL 冒烟 2 步 ─(通过)─▶ RL 正式 20 步 ─▶ 最终评测（原版 / coderteach / RL 同时跑）─▶ 报告
#   试点选 B（实时 Teacher）也照跑，总花费锁在 --budget-usd 120 内（B 的 API 贵，步数会少）。任何一步检查不过 → 停下。
# 结束后 GPU 不会自己停（Pod 的 key 无权限）→ 用户手动 Stop pod。
cd /root/work/agent_harness
T=/root/work/train
POD="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -p ${POD_PORT:?set POD_PORT} root@${POD_HOST:?set POD_HOST}"
say() { echo "$(TZ=America/New_York date +%H:%M) $*"; }
EVAL="qeval-base-synth qeval-plain-synth qeval-lora-synth qeval-skill-synth qeval-teach-synth qeval-base-synth-h0 qeval-teach-synth-h0 qeval-base-tb qeval-teach-tb"

# 1 SFT 评测结束 → 报告
for j in $EVAL; do until [ -f /root/work/jobs/$j.done ]; do sleep 60; done; done
PYTHONPATH=. .venv/bin/python tools/qeval_report.py --out /root/work/reports/qeval > /root/work/reports/qeval_stdout.txt 2>&1
say "SFT eval done; report at /root/work/reports/qeval/summary.md"

# 2 试点重跑（D-074）：条件与 D-069 的 B 相同——只挂原版的 vLLM、并发 16、没有别的 job；规则沿用已写好的（不再花 API）
if [ -f /root/work/jobs/qpilot-psp-rules2.done ]; then
  say "pilot rerun already done — reusing it (chain restarted, D-078)"
else
  # 关旧服务 + 起新服务写在 serve_plain.sh 里：命令行里不能出现 "vllm serve"，否则 pkill 会杀掉这条命令自己（22:09 事故）
  $POD "cat > /workspace/code/serve_plain.sh" < train/ambig/serve_plain.sh
  timeout 60 $POD 'setsid nohup bash /workspace/code/serve_plain.sh > /workspace/logs/serve_plain.txt 2>&1 < /dev/null &'
  for i in $(seq 1 120); do curl -sf -m 10 127.0.0.1:8000/v1/models | grep -q '"coder30b"' && break; sleep 15; done
  curl -sf -m 10 127.0.0.1:8000/v1/models | grep -q '"coder30b"' || { say "STOP: plain vLLM did not come up"; exit 1; }
  bash tools/launch_job.sh qpilot-psp-rules2 || { say "STOP: pilot rerun launch failed"; exit 1; }
  until [ -f /root/work/jobs/qpilot-psp-rules2.done ]; do sleep 60; done
fi
PYTHONPATH=. .venv/bin/python tools/psp_pilot_report.py --out /root/work/reports/psp_pilot --pilot-job qpilot-psp-rules2 > /root/work/reports/psp_pilot_stdout.txt 2>&1
# 用户 2026-09-27：选 B 也照跑，但 RL 总花费（GPU + Teacher 的 API）仍锁在已批的 120 美元内（grpo_loop 的 --budget-usd），到额度自动停
if grep -q "RL 难题提示用 A" /root/work/reports/psp_pilot/summary.md; then MODE=rules; else MODE=teacher; fi
say "pilot decision: $MODE — $(grep '决定' /root/work/reports/psp_pilot/summary.md)"

# 闸门：RunPod 余额不够跑完 RL 的话，Pod 会被停机、盘上的东西全丢 → 等用户确认充值后（由我 touch /root/work/RL_GO）再开始花 RL 的钱
[ -f /root/work/RL_GO ] || say "waiting for /root/work/RL_GO (user confirms the RunPod top-up)"
until [ -f /root/work/RL_GO ]; do sleep 60; done

# 3 RL 冒烟：3 道第一轮有对有错的题 + 1 道带规则的难题，2 步 × 4 次
SMOKE=data-transform--bird-survey-format-report,git-repair--recover-chess-round-four,sqlite-query--chess-club-upset-standings,data-transform--podcast-daily-download-report
PYTHONPATH=. .venv/bin/python train/rl/grpo_loop.py --hint-mode $MODE --rl-dir /root/work/rl_smoke --prefix smoke --steps 2 --tasks-per-step 4 \
    --attempts 4 --concurrency 16 --min-signal-groups 1 --budget-usd 15 --only-tasks $SMOKE > /root/work/rl_smoke.log 2>&1
python3 - <<'PY' || { say "STOP: RL smoke test failed (see /root/work/rl_smoke.log)"; exit 1; }
import json, sys
h = [json.loads(l) for l in open("/root/work/rl_smoke/log.jsonl")]
ok = len(h) == 2 and all((x.get("train") or {}).get("lora_b_norm", 0) > 0 for x in h) and "RL_LOOP_END at step 2" in open("/root/work/rl_smoke.log").read()
print("smoke:", [(x["step"], x["pass_rate"], x["batch"]["signal_groups"], (x.get("train") or {}).get("lora_b_norm"),
                  (x.get("train") or {}).get("peak_gpu_gb"), (x.get("train") or {}).get("dropped")) for x in h])
sys.exit(0 if ok else 1)
PY
say "RL smoke passed"

# 4 RL 正式
mkdir -p /root/work/rl
for try in 1 2 3; do   # 中途崩了（如连接断）就从断点接着跑；正常结束（含止损）会打印 RL_LOOP_END
  PYTHONPATH=. .venv/bin/python train/rl/grpo_loop.py --hint-mode $MODE --rl-dir /root/work/rl --prefix rl --steps 20 --budget-usd 120 >> /root/work/rl/loop.log 2>&1
  grep -q RL_LOOP_END /root/work/rl/loop.log && break
  say "RL loop crashed (try $try): $(tail -2 /root/work/rl/loop.log | tr '\n' ' ')"; sleep 60
done
grep -q RL_LOOP_END /root/work/rl/loop.log || { say "STOP: RL loop crashed 3 times"; exit 1; }
FINAL=$(python3 -c "import json; print(json.load(open('/root/work/rl/state.json'))['policy'])")
say "RL loop ended: $(tail -1 /root/work/rl/loop.log); final policy $FINAL"
[ "$FINAL" = rlpolicy00 ] && { say "STOP: RL never updated the policy"; exit 1; }

# 5 最终评测：同一个 vLLM 挂原版 + coderteach + 最终 RL，留出合成题 37 × 3、TB 30 × 4，六个 job 同时跑（D-040）
timeout 60 $POD "rm -f /workspace/logs/serve_lora.txt; setsid nohup bash /workspace/code/serve_lora.sh coderteach=/workspace/ckpt/coderteach $FINAL=/workspace/rl/$FINAL < /dev/null > /workspace/logs/serve_lora.stdout 2>&1 &"
until $POD 'grep -qE "SERVE_LORA_OK|ADAPTER_NOT_APPLIED|SERVE_FAILED" /workspace/logs/serve_lora.txt 2>/dev/null' 2>/dev/null; do sleep 30; done
$POD 'grep -E "adapter|SERVE" /workspace/logs/serve_lora.txt'
$POD 'grep -q SERVE_FAILED /workspace/logs/serve_lora.txt' && { say "STOP: vLLM did not come up"; exit 1; }
$POD 'grep -q "ADAPTER_NOT_APPLIED: coderteach" /workspace/logs/serve_lora.txt' && { say "STOP: coderteach not applied"; exit 1; }
# RL 适配器在温度 0 下 3 道题都与原版一样不算失败（20 步小学习率可能改得很少，这本身是结果）；它的权重变了由每步的 lora_b 范数证明
for arm in base teach rl; do
  for set in synth tb; do
    m=$([ $arm = base ] && echo coder30b || ([ $arm = teach ] && echo coderteach || echo $FINAL))
    sed -e "s|^job_name: .*|job_name: qfinal-$arm-$set|" -e "s|model_name: openai/[a-z0-9]*|model_name: openai/$m|" \
        -e "1s|^# .*|# D-072 最终评测：$arm × $set（与另外两臂同时跑）|" experiments/configs/qeval-teach-$set.resolved.yaml \
        > experiments/configs/qfinal-$arm-$set.resolved.yaml
  done
done
sleep 10
bash tools/launch_job.sh qfinal-base-synth qfinal-teach-synth qfinal-rl-synth qfinal-base-tb qfinal-teach-tb qfinal-rl-tb || { say "STOP: final eval launch failed"; exit 1; }
for j in qfinal-base-synth qfinal-teach-synth qfinal-rl-synth qfinal-base-tb qfinal-teach-tb qfinal-rl-tb; do until [ -f /root/work/jobs/$j.done ]; do sleep 60; done; done
PYTHONPATH=. .venv/bin/python tools/rl_eval_report.py --out /root/work/reports/rl_final
say "ALL_DONE — GPU is now idle: please Stop the pod"
