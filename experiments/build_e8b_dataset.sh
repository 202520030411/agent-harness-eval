#!/bin/bash
# 在服务器上执行：把 6 道题从 harbor 缓存复制到 /root/work/tasks_e8/，用改写后的 instruction.md 覆盖（对照题不覆盖）。
set -e
SRC=/root/.cache/harbor/tasks/packages/terminal-bench
DST=/root/work/tasks_e8b
RW=/root/work/agent_harness/experiments/e8b_rewrites
rm -rf "$DST"; mkdir -p "$DST"
for t in raman-fitting dna-insert; do
  d=$(ls -d $SRC/$t/*/ | head -1)
  cp -r "$d" "$DST/$t"
  if [ -f "$RW/$t/instruction.md" ]; then
    cp "$RW/$t/instruction.md" "$DST/$t/instruction.md"; echo "rewritten: $t"
  else
    echo "control (unchanged): $t"
  fi
done
ls "$DST"
