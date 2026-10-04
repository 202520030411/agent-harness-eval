#!/bin/bash
# 训练后评测用：同一个 vLLM 同时挂原版（coder30b）和一个或多个 LoRA，各臂同时跑（D-040）。
# 用法（Pod）：bash serve_lora.sh coderlora=/workspace/ckpt/coderlora coderplain=/workspace/ckpt/coderplain
# 每个适配器用温度 0 与原版各答 3 道题：若某个适配器 3 道都与原版一字不差，说明它没生效，打印 ADAPTER_NOT_APPLIED，不要开始评测。
set -uo pipefail
[ $# -ge 1 ] || { echo "usage: serve_lora.sh name=path [name=path ...]"; exit 1; }
V=/workspace/venv; M=/workspace/models/Qwen3-Coder-30B-A3B-Instruct; export PATH=$V/bin:$PATH
R=/workspace/logs/serve_lora.txt; : > $R
pkill -f "[v]llm serve"; sleep 15
nohup vllm serve $M --served-model-name coder30b --port 8000 --host 127.0.0.1 --max-model-len 131072 --gpu-memory-utilization 0.92 \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder \
    --enable-lora --max-lora-rank 16 --max-loras $# --lora-modules "$@" > /workspace/logs/vllm.log 2>&1 &
last=${!#}; last=${last%%=*}
for i in $(seq 1 180); do curl -s localhost:8000/v1/models | grep -q "\"$last\"" && break; sleep 5; done
curl -s localhost:8000/v1/models | grep -q "\"$last\"" || { echo "SERVE_FAILED" | tee -a $R; exit 1; }
ask() { curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' \
          -d "$(python -c 'import json,sys; print(json.dumps({"model":sys.argv[1],"messages":[{"role":"user","content":sys.argv[2]}],"max_tokens":120,"temperature":0}))' "$1" "$2")" \
        | python -c 'import json,sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"])'; }
bad=0
for kv in "$@"; do
  name=${kv%%=*}; same=0
  for q in "Write a bash one-liner that counts .py files under the current directory." \
           "In one sentence, what does git reflog show?" \
           "Give a SQL query that returns the 3 most recent rows of table events ordered by ts."; do
    a=$(ask coder30b "$q"); b=$(ask "$name" "$q")
    [ "$a" = "$b" ] && same=$((same + 1))
    printf '[%s] Q: %s\n  base: %s\n  lora: %s\n' "$name" "$q" "${a:0:140}" "${b:0:140}" >> $R
  done
  if [ $same -eq 3 ]; then echo "ADAPTER_NOT_APPLIED: $name (3/3 identical at T=0)" | tee -a $R; bad=1; else echo "adapter $name OK ($same/3 identical)" | tee -a $R; fi
done
[ $bad -eq 0 ] && echo "SERVE_LORA_OK" | tee -a $R
