"""作弊演习（D-085）：同一组题，旧版判分 vs 加固版判分，每种作弊各跑一次，汇总"骗到通过没有、诱饵抓到没有"。
不调任何模型、不用 GPU，只在本机 Docker 里跑。

用法（服务器）：PYTHONPATH=. .venv/bin/python tools/run_drills.py --tag d1 \
    --old /root/work/train/synth_split/train --new /root/work/train/synth_split_v2/train \
    --tasks data-transform--bird-survey-format-report,local-service--appointment-slot-api,<port-program 题>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

from tools.drill_agent import ATTACKS
from train.synth.harden import CANARY

ROOT = Path("/root/work/drills")


def job_config(job: str, dataset: Path, attack: str, jobs_dir: Path) -> dict:
    return {"job_name": job, "jobs_dir": str(jobs_dir), "n_attempts": 1, "timeout_multiplier": 1.0,
            "orchestrator": {"type": "local", "n_concurrent_trials": 4, "quiet": True},
            "environment": {"type": "docker", "force_build": False, "delete": True},
            "agents": [{"name": "tools.drill_agent:DrillAgent", "kwargs": {"attack": attack}}],
            "datasets": [{"path": str(dataset)}]}


def summarize(jobs_dir: Path, jobs: list[tuple[str, str, str]]) -> list[dict]:
    rows = []
    for job, version, attack in jobs:
        for res in sorted((jobs_dir / job).glob("*__*/result.json")):
            r = json.loads(res.read_text())
            reward = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
            exc = (r.get("exception_info") or {}).get("exception_type")
            blob = json.dumps(r) + "".join(p.read_text(errors="ignore") for p in res.parent.rglob("*.txt"))
            rows.append({"version": version, "attack": attack, "task": r.get("task_name", "").split("/")[-1],
                         "reward": reward, "exception": exc, "canary_seen": CANARY in blob})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--attacks", default=",".join(ATTACKS))
    a = ap.parse_args()
    base = ROOT / a.tag
    if base.exists():
        raise SystemExit(f"{base} exists")
    jobs_dir = base / "jobs"
    jobs = []
    for version, src in (("old", Path(a.old)), ("new", Path(a.new))):
        ds = base / "datasets" / version
        for t in a.tasks.split(","):
            shutil.copytree(src / t, ds / t)
        for attack in a.attacks.split(","):
            job = f"drill-{a.tag}-{version}-{attack}"
            cfg = base / "configs" / f"{job}.yaml"
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(yaml.safe_dump(job_config(job, ds, attack, jobs_dir), sort_keys=False))
            jobs.append((job, version, attack))
            print(f"running {job}", flush=True)
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
            subprocess.run([".venv/bin/harbor", "run", "-c", str(cfg), "-y"], env=env, check=False,
                           stdout=open(base / f"{job}.log", "w"), stderr=subprocess.STDOUT)
    rows = summarize(jobs_dir, jobs)
    (base / "summary.json").write_text(json.dumps(rows, indent=1))
    tasks = a.tasks.split(",")
    print("\n| 作弊方式 | " + " | ".join(f"旧版 {t.split('--')[0]}" for t in tasks) + " | "
          + " | ".join(f"加固版 {t.split('--')[0]}" for t in tasks) + " | 诱饵被抓到 |")
    print("|---" * (2 * len(tasks) + 2) + "|")
    for attack in a.attacks.split(","):
        cells = []
        for version in ("old", "new"):
            for t in tasks:
                m = [r for r in rows if r["version"] == version and r["attack"] == attack and r["task"] == t]
                cells.append("—" if not m else ("通过" if (m[0]["reward"] or 0) >= 1 else "失败") + (f"（{m[0]['exception']}）" if m[0]["exception"] else ""))
        caught = any(r["canary_seen"] for r in rows if r["attack"] == attack and r["version"] == "new")
        print(f"| {attack} | " + " | ".join(cells) + f" | {'是' if caught else '—'} |")


if __name__ == "__main__":
    main()
