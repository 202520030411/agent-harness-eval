"""老师轨迹 → SFT 数据（拒绝采样：只留通过的；缺约定题还要求提交前读过证据文件）。

输出 JSONL，每行 {"messages": [...], "task_id", "family", "turns"}；训练时只对 assistant 轮算 loss（见 sft_train.py）。
用法：python sft_data.py /root/work/train/teacher_*.jsonl --out /root/work/train/sft.jsonl [--max-turns 9]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def keep(r: dict, max_turns: int) -> bool:
    if r["reward"] < 1 or r["invalid"] > 0 or r["turns"] > max_turns:
        return False
    if r["needs_evidence"] and not r["read_evidence"]:
        return False
    return all(not m["content"].startswith("<<api error") for m in r["messages"])


def main(a):
    recs = [json.loads(l) for f in a.inputs for l in open(f) if l.strip()]
    kept = [r for r in recs if keep(r, a.max_turns)]
    # 每题最多留 per_task 条，避免同题重复
    seen = collections.Counter(); out = []
    for r in kept:
        if seen[r["task_id"]] >= a.per_task:
            continue
        seen[r["task_id"]] += 1
        out.append({"messages": r["messages"], "task_id": r["task_id"], "family": r["family"], "turns": r["turns"]})
    Path(a.out).write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n")
    fam = collections.Counter(x["family"] for x in out)
    print(f"read {len(recs)} episodes, kept {len(kept)} (pass & evidence & ≤{a.max_turns} turns & no invalid), wrote {len(out)}")
    print("by family:", dict(fam)); print("avg turns:", round(sum(x["turns"] for x in out) / max(1, len(out)), 2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-turns", type=int, default=9)
    ap.add_argument("--per-task", type=int, default=1)
    main(ap.parse_args())
