#!/usr/bin/env python3
"""把模板配置 + 题目清单 → 可直接 `harbor run -c` 的正式配置。

用法：
  python3 resolve.py configs/e1_baseline_seed.yaml --tasks task_list.txt --job e1-baseline-seed [--k 3] [--concurrency 8] [--agent terminus2_patches.agent:Terminus2Patched] [--set verifier_gate=auditor ...]

规则：
- 题名自动加 `terminal-bench/` 前缀（Harbor 用 fnmatch 匹配完整题名）。
- agent 是上游 `terminus-2` 时，删除我们的七个开关（上游会拒绝未知 kwargs）；
  agent 是我们的 fork（含 ":" 的 import 路径）时保留，并允许用 --set 覆盖。
- 输出写到 configs/<job>.resolved.yaml，jobs_dir 固定为 /root/work/jobs。
"""
import argparse, pathlib, sys, yaml

FLAGS = ["verifier_gate", "adaptive_wait", "wait_stable_sec", "wait_cap_sec", "task_contract", "contract_version",
         "deliverable_checkpoint", "checkpoint_after_sec", "checkpoint_repeat_sec"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("template")
    ap.add_argument("--tasks", required=True, help="题目清单文件，每行一个题名（不带前缀）")
    ap.add_argument("--job", required=True)
    ap.add_argument("--k", type=int)
    ap.add_argument("--concurrency", type=int)
    ap.add_argument("--agent", help="覆盖 agent：上游名（terminus-2）或 import 路径（module:Class）")
    ap.add_argument("--set", action="append", default=[], help="key=value，写入 agent kwargs（如 verifier_gate=auditor）")
    ap.add_argument("--out")
    a = ap.parse_args()

    cfg = yaml.safe_load(open(a.template, encoding="utf-8"))
    names = [t.strip() for t in pathlib.Path(a.tasks).read_text().splitlines() if t.strip() and not t.startswith("#")]
    cfg["datasets"][0]["task_names"] = [n if "/" in n else f"terminal-bench/{n}" for n in names]
    cfg["job_name"] = a.job
    cfg["jobs_dir"] = "/root/work/jobs"
    if a.k: cfg["n_attempts"] = a.k
    if a.concurrency: cfg.setdefault("orchestrator", {})["n_concurrent_trials"] = a.concurrency

    for ag in cfg["agents"]:
        if a.agent:
            ag["name"] = a.agent          # Harbor 0.23：import 路径也放在 name 里（--print-config 核对过）
        kw = ag.setdefault("kwargs", {}) or {}
        ag["kwargs"] = kw
        upstream = ag.get("name") == "terminus-2"
        if upstream:
            for f in FLAGS: kw.pop(f, None)
        for kv in a.set:
            k, v = kv.split("=", 1)
            if upstream: sys.exit(f"--set {k} 需要我们的 fork agent（--agent module:Class），上游 terminus-2 不认识它")
            kw[k] = yaml.safe_load(v)

    out = a.out or f"configs/{a.job}.resolved.yaml"
    yaml.safe_dump(cfg, open(out, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
    print(f"{out}: {len(names)} tasks, k={cfg['n_attempts']}, agent={cfg['agents'][0].get('name')}")

if __name__ == "__main__":
    main()
