#!/bin/bash
# 两轮采样 → SFT 数据（QWEN_PLAN §4.1、D-061、D-063）：
#   sft_plain.jsonl = 第一轮（普通采样）合格轨迹           → 训练 coderplain
#   sft_all.jsonl   = 第一轮 + 第二轮（删掉提示）合格轨迹   → 训练 coderlora
# 并写出训练数据构成 /root/work/train/sft_meta.md（按轮次、技能族、难度档；难度档 = 该题在第一轮 3 次里过几次）
set -euo pipefail
cd /root/work/agent_harness
T=/root/work/train
.venv/bin/python train/tb_sft_export.py --jobs /root/work/jobs/qroll-h2-synth-train --allow-fixed --out $T/sft_r1.jsonl | tee $T/sft_r1.log
.venv/bin/python train/tb_sft_export.py --jobs /root/work/jobs/qroll-h2-synth-train-hint --hints $T/hints_train.json --allow-fixed --out $T/sft_r2.jsonl | tee $T/sft_r2.log
cp $T/sft_r1.jsonl $T/sft_plain.jsonl
cat $T/sft_r1.jsonl $T/sft_r2.jsonl > $T/sft_all.jsonl
python3 - <<'PY'
import collections, glob, json
T = "/root/work/train"
passes = collections.defaultdict(list)
for f in glob.glob("/root/work/jobs/qroll-h2-synth-train/*__*/result.json"):
    r = json.load(open(f))
    if r.get("exception_info"):
        continue
    passes[r["task_name"].split("/")[-1]].append((((r.get("verifier_result") or {}).get("rewards") or {}).get("reward") or 0) >= 1)
tier = {t: ("0/3" if sum(v) == 0 else "3/3" if sum(v) == len(v) else "1–2/3") for t, v in passes.items()}
tiers_tasks = collections.Counter(tier.values())
L = ["| 来源 | 轨迹数 | 覆盖题数 | 按技能族 | 按难度档（第一轮 3 次里过几次） |", "|---|---|---|---|---|"]
for name in ("sft_r1", "sft_r2", "sft_all"):
    rows = [json.loads(l) for l in open(f"{T}/{name}.jsonl")]
    fam = collections.Counter(r["task"].split("--")[0] for r in rows)
    tr = collections.Counter(tier.get(r["task"], "?") for r in rows)
    L.append(f"| {name} | {len(rows)} | {len({r['task'] for r in rows})} | {dict(sorted(fam.items()))} | {dict(sorted(tr.items()))} |")
L += ["", f"训练题难度分布（第一轮）：{dict(sorted(tiers_tasks.items()))}；全过（3/3）的题太容易、全挂（0/3）的题第一轮没有样本（第二轮带提示可能有）。",
      "", "导出筛选的丢弃原因：", "", "- 第一轮：" + open(f"{T}/sft_r1.log").read().strip().splitlines()[-1], "- 第二轮：" + open(f"{T}/sft_r2.log").read().strip().splitlines()[-1]]
open(f"{T}/sft_meta.md", "w").write("\n".join(L) + "\n")
print("\n".join(L))
PY
