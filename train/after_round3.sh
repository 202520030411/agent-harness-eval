#!/bin/bash
# 第三轮结束后自动（D-067）：导出第三轮（删掉技能提示）→ sft_skill = 三轮合并 → 传到 Pod → 停 vLLM、后台训 coderskill →
# 适配器拷回 Hetzner → 同一个 vLLM 挂原版 + 三个适配器并逐个检查生效 → 通过才同时启动九个评测 job（含共同进化 2×2 的两个 H0 格子，D-068）。
# Pod 上的长任务一律 setsid nohup 放后台、本地 SSH 30 秒后断开、靠完成标记轮询（D-066：不能让断线把任务重跑或杀掉）。
cd /root/work/agent_harness
T=/root/work/train
POD="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -p ${POD_PORT:?set POD_PORT} root@${POD_HOST:?set POD_HOST}"
say() { echo "$(TZ=America/New_York date +%H:%M) $*"; }
until [ -f /root/work/jobs/qroll-h2-synth-train-skill.done ]; do sleep 30; done
say "round 3 done: $(python3 /root/work/job_status.py qroll-h2-synth-train-skill)"
.venv/bin/python train/tb_sft_export.py --jobs /root/work/jobs/qroll-h2-synth-train-skill --hints $T/hints_skill.json --allow-fixed --out $T/sft_r3.jsonl | tee $T/sft_r3.log
cat $T/sft_r1.jsonl $T/sft_r2.jsonl $T/sft_r3.jsonl > $T/sft_skill.jsonl
python3 - <<'PY'
import collections, json
T = "/root/work/train"
L = []
for name in ("sft_r3", "sft_skill"):
    rows = [json.loads(l) for l in open(f"{T}/{name}.jsonl")]
    fam = collections.Counter(r["task"].split("--")[0] for r in rows)
    L.append(f"| {name} | {len(rows)} | {len({r['task'] for r in rows})} | {dict(sorted(fam.items()))} | 第三轮全部来自前两轮 0 次做对的题 |")
L.append("- 第三轮：" + open(f"{T}/sft_r3.log").read().strip().splitlines()[-1])
open(f"{T}/sft_meta.md", "a").write("\n" + "\n".join(L) + "\n")
print("\n".join(L))
PY
$POD "cat > /workspace/data/sft_skill.jsonl" < $T/sft_skill.jsonl
say "training coderskill on $($POD 'wc -l < /workspace/data/sft_skill.jsonl') examples"
timeout 30 $POD 'rm -f /workspace/logs/train_skill_done.txt; pkill -f "[v]llm serve"; sleep 20; cd /workspace/code && setsid nohup bash -c "/workspace/venv/bin/python sft_train.py --data /workspace/data/sft_skill.jsonl --out /workspace/ckpt/coderskill --device-map cuda --drop-long --max-len 32768 --grad-accum 8 --epochs 2 --lr 1e-4 --rank 16 --thinking default > /workspace/logs/train_skill.log 2>&1; echo skill_rc=\$? > /workspace/logs/train_skill_done.txt" < /dev/null > /dev/null 2>&1 &'
until $POD 'test -f /workspace/logs/train_skill_done.txt' 2>/dev/null; do sleep 30; done
say "coderskill trained: $($POD 'cat /workspace/logs/train_skill_done.txt; tr "\r" "\n" < /workspace/logs/train_skill.log | grep -E "examples,|train_loss" | tr "\n" " "')"
$POD 'tar czf - -C /workspace/ckpt --exclude="checkpoint-*" coderskill' | tar xzf - -C $T/adapters/
ls -la $T/adapters/*/adapter_model.safetensors
timeout 30 $POD 'rm -f /workspace/logs/serve_lora.txt; setsid nohup bash /workspace/code/serve_lora.sh coderlora=/workspace/ckpt/coderlora coderplain=/workspace/ckpt/coderplain coderskill=/workspace/ckpt/coderskill < /dev/null > /workspace/logs/serve_lora.stdout 2>&1 &'
until $POD 'grep -qE "SERVE_LORA_OK|ADAPTER_NOT_APPLIED|SERVE_FAILED" /workspace/logs/serve_lora.txt 2>/dev/null' 2>/dev/null; do sleep 30; done
$POD 'grep -E "adapter|SERVE" /workspace/logs/serve_lora.txt'
if $POD 'grep -q SERVE_LORA_OK /workspace/logs/serve_lora.txt'; then
  sleep 10
  bash tools/launch_job.sh qeval-base-synth qeval-plain-synth qeval-lora-synth qeval-skill-synth qeval-base-synth-h0 qeval-skill-synth-h0 qeval-base-tb qeval-lora-tb qeval-skill-tb && say "EVAL_LAUNCHED"
else
  say "ADAPTER_CHECK_FAILED — not launching eval"
fi
