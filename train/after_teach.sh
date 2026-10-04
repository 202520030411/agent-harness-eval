#!/bin/bash
# D-069：实时 Teacher 轮结束后自动：导出（删掉提示）→ sft_teach = 第一、二轮 + 这一轮 → 后台训 coderteach → 适配器拷回 →
# 同一 vLLM 挂原版 + 四个适配器并逐个检查生效 → 通过才启动用户已批准的 9 组评测（D-070）。长任务一律后台 + 完成标记（D-066）。
cd /root/work/agent_harness
T=/root/work/train
POD="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -p ${POD_PORT:?set POD_PORT} root@${POD_HOST:?set POD_HOST}"
say() { echo "$(TZ=America/New_York date +%H:%M) $*"; }
until [ -f /root/work/jobs/qroll-h2-synth-train-teach.done ]; do sleep 30; done
say "teacher round done: $(python3 /root/work/job_status.py qroll-h2-synth-train-teach)"
.venv/bin/python train/tb_sft_export.py --jobs /root/work/jobs/qroll-h2-synth-train-teach --allow-fixed --out $T/sft_r4.jsonl | tee $T/sft_r4.log
cat $T/sft_r1.jsonl $T/sft_r2.jsonl $T/sft_r4.jsonl > $T/sft_teach.jsonl
python3 - <<'PY'
import collections, json
T = "/root/work/train"
L = []
for name in ("sft_r4", "sft_teach"):
    rows = [json.loads(l) for l in open(f"{T}/{name}.jsonl")]
    fam = collections.Counter(r["task"].split("--")[0] for r in rows)
    L.append(f"| {name} | {len(rows)} | {len({r['task'] for r in rows})} | {dict(sorted(fam.items()))} | 实时 Teacher 提示轮（D-069），题目是前两轮 0 次做对的 51 道 |")
L.append("- 实时 Teacher 轮：" + open(f"{T}/sft_r4.log").read().strip().splitlines()[-1])
open(f"{T}/sft_meta.md", "a").write("\n" + "\n".join(L) + "\n")
print("\n".join(L))
PY
$POD "cat > /workspace/data/sft_teach.jsonl" < $T/sft_teach.jsonl
say "training coderteach on $($POD 'wc -l < /workspace/data/sft_teach.jsonl') examples"
timeout 30 $POD 'rm -f /workspace/logs/train_teach_done.txt; pkill -f "[v]llm serve"; sleep 20; cd /workspace/code && setsid nohup bash -c "/workspace/venv/bin/python sft_train.py --data /workspace/data/sft_teach.jsonl --out /workspace/ckpt/coderteach --device-map cuda --drop-long --max-len 32768 --grad-accum 8 --epochs 2 --lr 1e-4 --rank 16 --thinking default > /workspace/logs/train_teach.log 2>&1; echo teach_rc=\$? > /workspace/logs/train_teach_done.txt" < /dev/null > /dev/null 2>&1 &'
until $POD 'test -f /workspace/logs/train_teach_done.txt' 2>/dev/null; do sleep 30; done
say "coderteach trained: $($POD 'cat /workspace/logs/train_teach_done.txt; tr "\r" "\n" < /workspace/logs/train_teach.log | grep -E "examples,|train_loss" | tr "\n" " "')"
$POD 'tar czf - -C /workspace/ckpt --exclude="checkpoint-*" coderteach' | tar xzf - -C $T/adapters/
ls -la $T/adapters/*/adapter_model.safetensors
timeout 30 $POD 'rm -f /workspace/logs/serve_lora.txt; setsid nohup bash /workspace/code/serve_lora.sh coderlora=/workspace/ckpt/coderlora coderplain=/workspace/ckpt/coderplain coderskill=/workspace/ckpt/coderskill coderteach=/workspace/ckpt/coderteach < /dev/null > /workspace/logs/serve_lora.stdout 2>&1 &'
until $POD 'grep -qE "SERVE_LORA_OK|ADAPTER_NOT_APPLIED|SERVE_FAILED" /workspace/logs/serve_lora.txt 2>/dev/null' 2>/dev/null; do sleep 30; done
$POD 'grep -E "adapter|SERVE" /workspace/logs/serve_lora.txt'
if $POD 'grep -q SERVE_LORA_OK /workspace/logs/serve_lora.txt'; then
  sleep 10   # 评测方案（9 组）用户已于 14:31 批准（D-070）
  bash tools/launch_job.sh qeval-base-synth qeval-plain-synth qeval-lora-synth qeval-skill-synth qeval-teach-synth qeval-base-synth-h0 qeval-teach-synth-h0 qeval-base-tb qeval-teach-tb && say "EVAL_LAUNCHED"
else
  say "ADAPTER_CHECK_FAILED — not launching eval"
fi
