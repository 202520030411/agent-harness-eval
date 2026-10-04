#!/bin/bash
# D-071 后半段（after_keep.sh 在训练启动后被停掉，训练已完成 keep_rc=0）：拷回 coderteach → 挂 4 个适配器并检查 → 启动 D-070 批准的 9 组评测。
cd /root/work/agent_harness
T=/root/work/train
POD="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -p ${POD_PORT:?set POD_PORT} root@${POD_HOST:?set POD_HOST}"
say() { echo "$(TZ=America/New_York date +%H:%M) $*"; }
say "coderteach (keep): $($POD 'cat /workspace/logs/train_keep_done.txt; tr "\r" "\n" < /workspace/logs/train_keep.log | grep -E "examples,|train_loss" | tr "\n" " "')"
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
