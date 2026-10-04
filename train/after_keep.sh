#!/bin/bash
# D-071：训练版 4 改用“提示留在对话里”的数据 → 备份删提示版 → 训新版 coderteach → 拷回 → 挂 4 个适配器并检查 → 启动 D-070 批准的 9 组评测。
cd /root/work/agent_harness
T=/root/work/train
POD="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -p ${POD_PORT:?set POD_PORT} root@${POD_HOST:?set POD_HOST}"
say() { echo "$(TZ=America/New_York date +%H:%M) $*"; }
.venv/bin/python train/tb_sft_export.py --jobs /root/work/jobs/qroll-h2-synth-train-teach --allow-fixed --keep-teacher-hints --out $T/sft_r4_keep.jsonl | tee $T/sft_r4_keep.log
cat $T/sft_r1.jsonl $T/sft_r2.jsonl $T/sft_r4_keep.jsonl > $T/sft_teach_keep.jsonl
python3 - <<'PY'
import collections, json
T = "/root/work/train"
rows = [json.loads(l) for l in open(f"{T}/sft_r4_keep.jsonl")]
allr = [json.loads(l) for l in open(f"{T}/sft_teach_keep.jsonl")]
fam = collections.Counter(r["task"].split("--")[0] for r in rows)
L = [f"| sft_r4_keep | {len(rows)} | {len({r['task'] for r in rows})} | {dict(sorted(fam.items()))} | 实时 Teacher 轮，提示留在对话里（D-071） |",
     f"| sft_teach_keep（训练版 4） | {len(allr)} | {len({r['task'] for r in allr})} | — | 第一、二轮 + 上一行 |",
     "- 实时 Teacher 轮（保留提示）：" + open(f"{T}/sft_r4_keep.log").read().strip().splitlines()[-1]]
open(f"{T}/sft_meta.md", "a").write("\n" + "\n".join(L) + "\n"); print("\n".join(L))
PY
mkdir -p $T/adapters/coderteach_strip
$POD 'tar czf - -C /workspace/ckpt/coderteach --exclude="checkpoint-*" .' | tar xzf - -C $T/adapters/coderteach_strip/
$POD "cat > /workspace/data/sft_teach_keep.jsonl" < $T/sft_teach_keep.jsonl
say "training coderteach (keep hints) on $($POD 'wc -l < /workspace/data/sft_teach_keep.jsonl') examples"
timeout 30 $POD 'rm -f /workspace/logs/train_keep_done.txt; pkill -f "[v]llm serve"; rm -rf /workspace/ckpt/coderteach_strip; mv /workspace/ckpt/coderteach /workspace/ckpt/coderteach_strip; cd /workspace/code && setsid nohup bash -c "/workspace/venv/bin/python sft_train.py --data /workspace/data/sft_teach_keep.jsonl --out /workspace/ckpt/coderteach --device-map cuda --drop-long --max-len 32768 --grad-accum 8 --epochs 2 --lr 1e-4 --rank 16 --thinking default > /workspace/logs/train_keep.log 2>&1; echo keep_rc=\$? > /workspace/logs/train_keep_done.txt" < /dev/null > /dev/null 2>&1 &'
until $POD 'test -f /workspace/logs/train_keep_done.txt' 2>/dev/null; do sleep 30; done
say "coderteach (keep) trained: $($POD 'cat /workspace/logs/train_keep_done.txt; tr "\r" "\n" < /workspace/logs/train_keep.log | grep -E "examples,|train_loss" | tr "\n" " "')"
rm -rf $T/adapters/coderteach && mkdir -p $T/adapters/coderteach
$POD 'tar czf - -C /workspace/ckpt/coderteach --exclude="checkpoint-*" .' | tar xzf - -C $T/adapters/coderteach/
ls -la $T/adapters/*/adapter_model.safetensors
timeout 30 $POD 'rm -f /workspace/logs/serve_lora.txt; setsid nohup bash /workspace/code/serve_lora.sh coderlora=/workspace/ckpt/coderlora coderplain=/workspace/ckpt/coderplain coderskill=/workspace/ckpt/coderskill coderteach=/workspace/ckpt/coderteach < /dev/null > /workspace/logs/serve_lora.stdout 2>&1 &'
until $POD 'grep -qE "SERVE_LORA_OK|ADAPTER_NOT_APPLIED|SERVE_FAILED" /workspace/logs/serve_lora.txt 2>/dev/null' 2>/dev/null; do sleep 30; done
$POD 'grep -E "adapter|SERVE" /workspace/logs/serve_lora.txt'
if $POD 'grep -q SERVE_LORA_OK /workspace/logs/serve_lora.txt'; then
  sleep 10   # D-070 批准的 9 组评测；D-071 用户选“不删”
  bash tools/launch_job.sh qeval-base-synth qeval-plain-synth qeval-lora-synth qeval-skill-synth qeval-teach-synth qeval-base-synth-h0 qeval-teach-synth-h0 qeval-base-tb qeval-teach-tb && say "EVAL_LAUNCHED"
else
  say "ADAPTER_CHECK_FAILED — not launching eval"
fi
