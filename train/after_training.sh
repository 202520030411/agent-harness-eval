#!/bin/bash
# 两个 LoRA 训完后自动：适配器拷回 Hetzner（Pod 余额耗尽或停机也不丢）→ 同一个 vLLM 挂原版 + 两个适配器并检查生效 →
# 通过才启动五个评测 job（D-063 / §4.1，同时启动）；检查不通过就停下报警。
cd /root/work/agent_harness
POD="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -p ${POD_PORT:?set POD_PORT} root@${POD_HOST:?set POD_HOST}"
until $POD 'grep -q TRAIN_DONE /workspace/logs/train_done.txt 2>/dev/null'; do sleep 30; done
echo "$(TZ=America/New_York date +%H:%M) training done: $($POD 'tr "\n" " " < /workspace/logs/train_done.txt')"
mkdir -p /root/work/train/adapters
$POD 'tar czf - -C /workspace/ckpt --exclude="checkpoint-*" coderplain coderlora' | tar xzf - -C /root/work/train/adapters/
ls -la /root/work/train/adapters/*/adapter_model.safetensors
$POD 'grep -hE "examples,|train_loss" /workspace/logs/train_plain.log /workspace/logs/train_all.log | tr "\r" "\n" | grep -E "examples,|train_loss"'
echo "$(TZ=America/New_York date +%H:%M) serving base + both adapters"
$POD 'bash /workspace/code/serve_lora.sh coderlora=/workspace/ckpt/coderlora coderplain=/workspace/ckpt/coderplain' | tail -4
if $POD 'grep -q SERVE_LORA_OK /workspace/logs/serve_lora.txt'; then
  sleep 5
  bash tools/launch_job.sh qeval-base-synth qeval-plain-synth qeval-lora-synth qeval-base-tb qeval-lora-tb && echo "$(TZ=America/New_York date +%H:%M) EVAL_LAUNCHED"
else
  echo "$(TZ=America/New_York date +%H:%M) ADAPTER_CHECK_FAILED — not launching eval"
fi
