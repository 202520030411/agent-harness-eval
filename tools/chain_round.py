"""一轮评测的服务器端接续（D-087 的教训：夜里的下一步不能靠我被叫醒）。在 tmux 里跑，全程写日志（美东时间）。

  python tools/chain_round.py --tag r2 [--replicate-if-accepted v0+c04 --rep-tag r2rep]

1. 等这一轮所有 job 结束（<job>.done）；30 分钟没有新完成的 trial → 写 ALERT 并退出（不再往下走）。
2. 每一臂 observe，每个候选 evaluate（用 plan 写的 .loop.json，判分代码指纹不对会被 evaluate 拒绝）。
3. 只有用户事先同意的复现（--replicate-if-accepted）才会自动开：该版本这次判 ACCEPT_* 或 PROVISIONAL 时，
   plan --replicate、launch，然后对复现批重复 1–2。其他情况一律停下等人。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
JOBS = Path("/root/work/jobs")
CONFIGS = REPO / "experiments/configs"
REPORTS = Path("/root/work/reports/loop")
PY = str(REPO / ".venv/bin/python")
ACCEPTING = {"ACCEPT_QUALITY", "ACCEPT_EFFICIENCY", "PROVISIONAL"}


def log(msg: str) -> None:
    print(f"[{datetime.now(ZoneInfo('America/New_York')):%Y-%m-%d %H:%M %Z}] {msg}", flush=True)


def run(args: list[str]) -> subprocess.CompletedProcess:
    log("$ " + " ".join(args))
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO)})


def sidecars(tag: str) -> list[dict]:
    out = []
    for f in sorted(CONFIGS.glob(f"loop-{tag}-*.loop.json")):
        sc = json.loads(f.read_text())
        sc["job"] = f.name[: -len(".loop.json")]
        out.append(sc)
    if not out:
        sys.exit(f"no sidecars for tag {tag}")
    return out


def _recent_connection_errors(jobs: list[str], last: int = 10) -> int:
    """最近完成的 last 个 trial 里有几个是"连不上模型"（D-094：断线时 trial 反而完成得更快，30 分钟没进展的检查抓不到）。"""
    files = sorted((f for j in jobs for f in (JOBS / j).glob("*__*/result.json")), key=lambda f: f.stat().st_mtime)[-last:]
    n = 0
    for f in files:
        try:
            msg = (json.loads(f.read_text()).get("exception_info") or {}).get("exception_message") or ""
        except Exception:  # noqa: BLE001
            continue
        n += "Connection error" in msg or "Connection refused" in msg
    return n


def wait(jobs: list[str], stall_min: int = 30) -> bool:
    last_n, last_t = -1, time.time()
    while True:
        done = sum((JOBS / f"{j}.done").exists() for j in jobs)
        n = sum(len(list((JOBS / j).glob("*__*/result.json"))) for j in jobs)
        if _recent_connection_errors(jobs) >= 3:
            log(f"ALERT: at least 3 of the last 10 finished trials could not reach the model ({n} trials so far); "
                "stopping the chain (the pod may be down or out of credit)")
            return False
        if done == len(jobs):
            log(f"all {len(jobs)} jobs done ({n} trials)")
            return True
        if n != last_n:
            last_n, last_t = n, time.time()
        elif time.time() - last_t > stall_min * 60:
            log(f"ALERT: no trial finished for {stall_min} minutes ({n} trials so far); stopping the chain")
            return False
        time.sleep(60)


def evaluate_round(tag: str, anchor_rows: str) -> dict[str, str]:
    scs = sidecars(tag)
    jobs = [sc["job"] for sc in scs]
    if not wait(jobs):
        return {}
    for sc in scs:
        r = run([PY, "tools/loop_cycle.py", "observe", "--jobs", sc["job"], "--arm", sc["arm"], "--out", str(REPORTS / tag / sc["arm"])])
        if r.returncode:
            log(f"observe failed for {sc['job']}: {r.stderr[-500:]}")
    decisions = {}
    for sc in scs:
        if sc["arm"] == "base":
            continue
        r = run([PY, "tools/loop_cycle.py", "evaluate", "--version", sc["version"], "--baseline-job", sc["baseline_job"],
                 "--candidate-job", sc["job"], "--anchor-rows", anchor_rows])
        (REPORTS / tag / f"evaluate_{sc['arm']}.json").write_text(r.stdout or r.stderr)
        try:
            d = json.loads(r.stdout)["decision"]
        except Exception:  # noqa: BLE001
            d = f"ERROR: {(r.stderr or r.stdout)[-300:]}"
        decisions[sc["version"]] = d
        log(f"{sc['version']} ({sc['purpose']}): {d}")
    return decisions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="")
    ap.add_argument("--anchor-rows", default=str(REPORTS / "r1/base/rows.jsonl"))
    ap.add_argument("--replicate-if-accepted", help="用户事先同意自动复现的版本")
    ap.add_argument("--rep-tag")
    ap.add_argument("--rep-concurrency", type=int, default=16, help="复现批的总并发（D-092：16 和 32 的单次用时一样，32 的吞吐翻倍）")
    ap.add_argument("--skip-round", action="store_true", help="这一轮已经判过（只从复现批开始）")
    ap.add_argument("--rep-only", action="store_true", help="--tag 本身就是复现批（重跑），直接等它、判它")
    ap.add_argument("--final-tag", help="复现 ACCEPT 后：promote，再启动事先写好的最终报告（tools/final_report.py write）")
    ap.add_argument("--template", default=str(CONFIGS / "loop-template-v2.yaml"))
    ap.add_argument("--final-only", action="store_true", help="只跑最终报告（D-096）：等 loop-<final-tag>-* 这 4 个 job，然后写报告")
    a = ap.parse_args()
    if a.final_only:
        jobs = [f.name[: -len(".resolved.yaml")] for f in sorted(CONFIGS.glob(f"loop-{a.final_tag}-*.resolved.yaml"))]
        if wait(jobs):
            r = run([PY, "tools/final_report.py", "report", "--tag", a.final_tag])
            log(f"final report written: {(r.stdout or r.stderr)[-1500:]}")
        log("chain finished. The pod stops itself after 30 idle minutes.")
        return
    if a.rep_only:                                         # 重跑的复现批（D-094）：直接等、判，然后进最终报告
        rep = evaluate_round(a.tag, a.anchor_rows)
        log(f"replication finished: {rep}")
        final_step(a, rep)
        return
    decisions = evaluate_round(a.tag, a.anchor_rows)
    v = a.replicate_if_accepted
    if not v or decisions.get(v) not in ACCEPTING:
        log(f"chain finished: {decisions}; no automatic follow-up. Waiting for a human (stop the pod if nothing else is planned).")
        return
    log(f"{v} was {decisions[v]} and the user pre-approved its replication: planning {a.rep_tag}")
    r = run([PY, "tools/loop_cycle.py", "plan", "--template", a.template, "--replicate", v, "--n-tasks", "74", "--tag", a.rep_tag,
             "--anchor-rows", a.anchor_rows, "--concurrency", str(a.rep_concurrency)])
    if r.returncode:
        log(f"plan failed: {r.stderr[-800:]}")
        return
    jobs = [sc["job"] for sc in sidecars(a.rep_tag)]
    r = subprocess.run(["bash", "tools/launch_job.sh", *jobs], cwd=REPO, capture_output=True, text=True)
    log(f"launch: {r.stdout.strip()} {r.stderr.strip()[-300:]}")
    if r.returncode:
        return
    rep = evaluate_round(a.rep_tag, a.anchor_rows)
    log(f"replication finished: {rep}")
    final_step(a, rep)


def final_step(a, rep: dict[str, str]) -> None:
    """复现 ACCEPT_* → promote → 启动最终报告的 4 个 job → 等 → 写报告。其他情况停下等人。"""
    v = a.replicate_if_accepted
    if not a.final_tag or rep.get(v) not in {"ACCEPT_QUALITY", "ACCEPT_EFFICIENCY"}:
        log(f"no final report started ({rep.get(v)}). Waiting for a human; the pod stops itself after 30 idle minutes.")
        return
    r = run([PY, "tools/loop_cycle.py", "promote", "--version", v])
    log(f"promote: {r.stdout.strip()} {r.stderr.strip()[-300:]}")
    if r.returncode:
        return
    jobs = [f.name[: -len(".resolved.yaml")] for f in sorted(CONFIGS.glob(f"loop-{a.final_tag}-*.resolved.yaml"))]
    if len(jobs) != 4:
        log(f"final report configs missing ({jobs}); stopping")
        return
    r = subprocess.run(["bash", "tools/launch_job.sh", *jobs], cwd=REPO, capture_output=True, text=True)
    log(f"launch final: {r.stdout.strip()} {r.stderr.strip()[-300:]}")
    if r.returncode or not wait(jobs):
        return
    r = run([PY, "tools/final_report.py", "report", "--tag", a.final_tag])
    log(f"final report written: {(r.stdout or r.stderr)[-1500:]}")
    log("chain finished. The pod stops itself after 30 idle minutes.")


if __name__ == "__main__":
    main()
