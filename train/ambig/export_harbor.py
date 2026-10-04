"""把合成题导出成 Harbor 本地任务目录，用 Terminus 2 + Docker 做“真实 harness 下”的评测（训练用的是进程内环境）。

每题：instruction.md（同一句题面 + “文件在 /app、答案写进 /app/answer.txt”）、environment/（python:3.11-slim + 工作区文件）、
tests/（期望答案 + 判分脚本，agent 看不到）、solution/solve.sh（写出标准答案，供 oracle 自检）。
用法：python export_harbor.py --split heldout --n 60 --out /root/work/train/harbor_ambig_heldout
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generator import make_split  # noqa: E402
from rollout import SPLITS  # noqa: E402

TASK_TOML = """schema_version = "1.1"
artifacts = []

[task]
name = "ambig/{tid}"
description = "Synthetic task: a convention is missing from the instruction but present in the workspace ({family})."
keywords = ["synthetic", "ambiguity", "{family}"]

[metadata]
author_name = "agent_harness"
author_email = "unknown"
difficulty = "easy"
category = "synthetic-ambiguity"
tags = ["synthetic", "{family}", "{kind}"]

[verifier]
timeout_sec = 120.0

[agent]
timeout_sec = 600.0

[environment]
build_timeout_sec = 600.0
cpus = 1
memory_mb = 1024
"""

DOCKERFILE = """FROM python:3.11-slim
WORKDIR /app
COPY workspace/ /app/
RUN mkdir -p /logs
"""

CHECK_PY = r'''import json, sys
exp = json.load(open("/tests/expected.json"))
try:
    got = open("/app/answer.txt").read().replace("\r\n", "\n").strip()
except FileNotFoundError:
    print("no /app/answer.txt"); sys.exit(1)
kind, ans = exp["kind"], exp["answer"]
ok = False
if kind == "json":
    try: ok = json.loads(got) == json.loads(ans)
    except Exception: ok = False
elif kind == "scalar_or_total":
    try:
        o = json.loads(got)
        if isinstance(o, dict) and set(o) == {"total"}: got = str(o["total"])
    except Exception: pass
    ok = got.strip().strip('"') == ans
else:
    norm = lambda x: "\n".join(l.rstrip() for l in x.strip().split("\n"))
    ok = norm(got) == norm(ans)
print("expected:", repr(ans)); print("got:", repr(got)); print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
'''

TEST_SH = """#!/bin/bash
mkdir -p /logs/verifier
if python3 /tests/check.py; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
"""


def export(tasks, out: Path):
    if out.exists():
        shutil.rmtree(out)
    for t in tasks:
        d = out / t.task_id
        (d / "environment" / "workspace").mkdir(parents=True)
        (d / "tests").mkdir()
        (d / "solution").mkdir()
        instr = (t.instruction.replace("submit", "write").replace("Submit", "Write")
                 + "\n\nThe project files are in /app. Write your final answer (and nothing else) to /app/answer.txt.\n")
        (d / "instruction.md").write_text(instr)
        (d / "task.toml").write_text(TASK_TOML.format(tid=t.task_id, family=t.family, kind="evidence" if t.needs_evidence else "clear"))
        (d / "environment" / "Dockerfile").write_text(DOCKERFILE)
        for p, c in t.files.items():
            f = d / "environment" / "workspace" / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(c)
        (d / "tests" / "expected.json").write_text(json.dumps({"kind": t.answer_kind, "answer": t.answer}))
        (d / "tests" / "check.py").write_text(CHECK_PY)
        (d / "tests" / "test.sh").write_text(TEST_SH)
        (d / "solution" / "solve.sh").write_text("#!/bin/bash\ncat > /app/answer.txt <<'ANSWER_EOF'\n" + t.answer + "\nANSWER_EOF\n")
        for f in (d / "tests" / "test.sh", d / "solution" / "solve.sh"):
            f.chmod(0o755)
    meta = [{"task_id": t.task_id, "family": t.family, "needs_evidence": t.needs_evidence, "evidence_path": t.evidence_path} for t in tasks]
    (out / "_index.json").write_text(json.dumps(meta, indent=1))
    print(f"exported {len(tasks)} tasks to {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="heldout")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--mix", action="store_true")
    ap.add_argument("--difficulty", choices=["easy", "hard"], default="easy")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    export(make_split(a.n, SPLITS[a.split], needs_evidence=None if a.mix else True, difficulty=a.difficulty), Path(a.out))
