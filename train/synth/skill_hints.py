"""第三轮（D-067）：给两轮都没做对的训练题生成“技能提示”，拷一份带提示的题目目录。
gpt-6-sol 读题面 + 参考解 + /app 文件清单，写 ≤ 5 句思路（方法与易错点；不给代码、命令、最终答案）。
提示与参考解有 8 词连续重合或含代码块的，丢弃（该题不进第三轮）。提示原文写 hints_skill.json，供导出时从题面里删掉。
用法：python train/synth/skill_hints.py --tasks-dir /root/work/train/synth_split/train --jobs /root/work/jobs/qroll-h2-synth-train /root/work/jobs/qroll-h2-synth-train-hint \
        --dst /root/work/train/synth_split/train_skill --hints-out /root/work/train/hints_skill.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agenteval.judge.client import JudgeClient  # noqa: E402

SYSTEM = ("You coach an AI coding agent that works in a Linux terminal. It attempted the task below several times and failed every time. "
          "Write a short hint (at most 5 sentences) that would help a capable engineer succeed: the approach to take and the specific "
          "pitfalls to watch for. Do NOT include code, shell commands, file contents, regular expressions, SQL, or any final values or "
          "expected outputs. Plain prose only. Reply with the hint text and nothing else.")
_W = re.compile(r"\w+")


def grams(t: str, n: int = 8) -> set:
    w = [x.lower() for x in _W.findall(t or "")]
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def zero_success(tasks: list[str], jobs: list[str]) -> list[str]:
    ok = set()
    for j in jobs:
        for f in Path(j).glob("*__*/result.json"):
            r = json.load(open(f))
            if (((r.get("verifier_result") or {}).get("rewards") or {}).get("reward") or 0) >= 1:
                ok.add(r["task_name"].split("/")[-1])
    return [t for t in tasks if t not in ok]


def main(a) -> None:
    src = Path(a.tasks_dir)
    todo = zero_success(sorted(p.name for p in src.iterdir() if p.is_dir()), a.jobs)
    print(f"{len(todo)} training tasks with zero successes in rounds 1–2")
    cost = {"in": 0, "out": 0}

    def one(t: str):
        d = src / t
        files = sorted(str(p.relative_to(d / "environment" / "workspace")) for p in (d / "environment" / "workspace").rglob("*") if p.is_file())
        sol = (d / "solution" / "solve.sh").read_text()
        user = (f"TASK INSTRUCTION:\n{(d / 'instruction.md').read_text()}\n\nFILES IN /app:\n" + "\n".join(files[:60])
                + f"\n\nREFERENCE SOLUTION (for you only; never quote it):\n{sol[:12000]}")
        cli = JudgeClient(a.model, reasoning_effort="medium", max_tokens=4000)
        hint = cli.complete(SYSTEM, user).strip()
        cost["in"] += cli.usage["prompt_tokens"]; cost["out"] += cli.usage["completion_tokens"]
        bad = "```" in hint or bool(grams(hint) & grams(sol)) or not hint
        return t, hint, bad

    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, todo))
    dst = Path(a.dst)
    if dst.exists():
        shutil.rmtree(dst)
    hints, dropped = {}, []
    for t, hint, bad in results:
        if bad:
            dropped.append(t); continue
        shutil.copytree(src / t, dst / t)
        block = "\n\nHint: " + " ".join(hint.split())
        f = dst / t / "instruction.md"
        f.write_text(f.read_text().rstrip() + block + "\n")
        hints[t] = block
    Path(a.hints_out).write_text(json.dumps(hints, indent=1, ensure_ascii=False))
    usd = cost["in"] * 2e-6 + cost["out"] * 1e-5
    print(f"hints kept {len(hints)}, dropped {len(dropped)} {dropped[:5]}; spend ${usd:.2f}")
    for t in list(hints)[:2]:
        print(f"--- {t}\n{hints[t].strip()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", required=True)
    ap.add_argument("--jobs", nargs="+", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--hints-out", required=True)
    ap.add_argument("--model", default="gpt-6-sol")
    main(ap.parse_args())
