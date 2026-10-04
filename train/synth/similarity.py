"""合成题 vs TB 2.1 全部 89 题的相似度过滤（QWEN_PLAN §4.1 防污染）。
对每道合成题：题面的 5 词连续片段里，有多大比例出现在某一道 TB 题的题面里（取最大的那道）。≥ 阈值就丢。
用法：python train/synth/similarity.py --tasks /root/work/train/synth_tasks --out /root/work/train/synth_similarity.json [--drop 0.15]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TB_ROOT = Path("/root/.cache/harbor/tasks/packages/terminal-bench")
_WORD = re.compile(r"[a-z0-9]+")


def grams(text: str, n: int = 5) -> set[tuple[str, ...]]:
    w = _WORD.findall(text.lower())
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def tb_instructions() -> dict[str, set]:
    out = {}
    for d in TB_ROOT.iterdir():
        files = sorted(d.glob("*/instruction.md"), key=lambda p: p.stat().st_mtime)
        if files:
            out[d.name] = grams(files[-1].read_text(errors="ignore"))
    return out


def main(a) -> None:
    tb = tb_instructions()
    rows = []
    for t in sorted(Path(a.tasks).iterdir()):
        f = t / "instruction.md"
        if not f.exists():
            continue
        g = grams(f.read_text())
        best, name = 0.0, None
        for k, tg in tb.items():
            c = len(g & tg) / max(1, len(g))
            if c > best:
                best, name = c, k
        rows.append({"task": t.name, "max_containment": round(best, 4), "closest_tb": name, "drop": best >= a.drop})
    rows.sort(key=lambda r: -r["max_containment"])
    Path(a.out).write_text(json.dumps({"n_tb": len(tb), "threshold": a.drop, "rows": rows}, indent=1))
    print(f"compared {len(rows)} synthetic tasks against {len(tb)} TB instructions; dropped {sum(r['drop'] for r in rows)}")
    for r in rows[:8]:
        print(f"  {r['max_containment']:.3f}  {r['task']}  ~ {r['closest_tb']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--drop", type=float, default=0.15)
    main(ap.parse_args())
