"""合成题校验结果 → 合格题清单与训练 / 留出划分（QWEN_PLAN §4.1）。
合格 = 参考解（oracle）通过 且 什么都不做（nop）不通过，两次都没有基础设施报错。划分按技能族分层、固定随机种子。
用法：python train/synth/collect_valid.py --oracle-job /root/work/jobs/synth-val-oracle --nop-job /root/work/jobs/synth-val-nop \
        --out /root/work/train/synth_split.json [--heldout-frac 0.33]
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import shutil
from pathlib import Path


def rewards(job: str) -> dict[str, tuple[float | None, str | None]]:
    out = {}
    for d in Path(job).glob("*__*/"):
        try:
            r = json.load(open(d / "result.json"))
        except Exception:  # noqa: BLE001
            continue
        task = r["task_name"].split("/")[-1]
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        out[task] = (rew, (r.get("exception_info") or {}).get("exception_type"))
    return out


def main(a) -> None:
    orc, nop = rewards(a.oracle_job), rewards(a.nop_job)
    too_similar = set()
    if a.similarity:
        too_similar = {r["task"] for r in json.load(open(a.similarity))["rows"] if r["drop"]}
    valid, why = [], collections.Counter()
    for t in sorted(set(orc) | set(nop)):
        (ro, eo), (rn, en) = orc.get(t, (None, "missing")), nop.get(t, (None, "missing"))
        if t in too_similar:
            why["too_similar_to_tb"] += 1
        elif eo or en:
            why[f"error:{eo or en}"] += 1
        elif not (ro is not None and ro >= 1):
            why["oracle_fails"] += 1
        elif rn is not None and rn >= 1:
            why["nop_passes"] += 1
        else:
            valid.append(t); why["valid"] += 1
    by_fam = collections.defaultdict(list)
    for t in valid:
        by_fam[t.split("--")[0]].append(t)
    rng = random.Random(a.seed)
    split = {"train": [], "heldout": []}
    for fam, ts in sorted(by_fam.items()):
        ts = sorted(ts); rng.shuffle(ts)
        k = round(len(ts) * a.heldout_frac)
        split["heldout"] += ts[:k]; split["train"] += ts[k:]
    Path(a.out).write_text(json.dumps({"why": dict(why), "by_family": {f: len(v) for f, v in by_fam.items()}, **split}, indent=1))
    print("validation:", dict(why)); print("by family:", {f: len(v) for f, v in sorted(by_fam.items())})
    print(f"split: train {len(split['train'])}, heldout {len(split['heldout'])} -> {a.out}")
    if a.tasks and a.materialize:   # 两个 Harbor 数据集目录：训练题 / 留出题（拷贝，互不影响）
        for part in ("train", "heldout"):
            dst = Path(a.materialize) / part
            if dst.exists():
                shutil.rmtree(dst)
            dst.mkdir(parents=True)
            for t in split[part]:
                shutil.copytree(Path(a.tasks) / t, dst / t)
            print(f"  {part}: {len(split[part])} task dirs -> {dst}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle-job", required=True)
    ap.add_argument("--nop-job", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--heldout-frac", type=float, default=1 / 3)
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--similarity", help="similarity.py 的输出；标了 drop 的题不算合格")
    ap.add_argument("--tasks", help="构建好的全部题目目录（与 --materialize 一起用）")
    ap.add_argument("--materialize", help="把训练 / 留出题分别拷到 <dir>/train 与 <dir>/heldout")
    main(ap.parse_args())
