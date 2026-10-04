"""给训练题加一条通用的行为提示（QWEN_PLAN §4 “给提示的 rollout，训练时删掉”；D-061）：拷一份题目目录，题面末尾追加 HINT。
训练导出时用 hints.json 把这段原文从第一条 user 消息里删掉（train/tb_sft_export.py --hints）。
用法：python train/synth/make_hinted.py --src /root/work/train/synth_split/train --dst /root/work/train/synth_split/train_hinted --hints-out /root/work/train/hints_train.json
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

HINT = ("Hint: /app contains material you can use to check your work (for example sample inputs with their expected outputs, "
        "or a checker script). Before you mark the task complete, run that check yourself, compare the result exactly, and fix "
        "any difference you find.")


def main(a) -> None:
    src, dst = Path(a.src), Path(a.dst)
    if dst.exists():
        shutil.rmtree(dst)
    hints = {}
    for t in sorted(p for p in src.iterdir() if p.is_dir()):
        shutil.copytree(t, dst / t.name)
        f = dst / t.name / "instruction.md"
        f.write_text(f.read_text().rstrip() + "\n\n" + HINT + "\n")
        hints[t.name] = "\n\n" + HINT
    Path(a.hints_out).write_text(json.dumps(hints, indent=1))
    print(f"{len(hints)} hinted tasks -> {dst}; hint strings -> {a.hints_out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--hints-out", required=True)
    main(ap.parse_args())
