"""最终报告（D-095）：最终版本 vs 起点 v0，在从没用来挑改动的题上（留出合成题 37 道 + TB 2.1 的 30 道）。只报告、不做决定。

  python tools/final_report.py write --tag final --k 4      # 只写 4 个 Harbor 配置（两臂 × 两个题集），不启动
  python tools/final_report.py report --tag final           # 跑完后：每个题集按题配对比较（用接受门的同一套统计），写 markdown

两臂的配置直接从第 2 轮的两臂复制（同一份 harness、同一个模型服务），只换题集、次数和并发；两臂同时启动（D-040）。
TB 的判分没有加固（和做题同一个容器）：报告里单列作弊巡查（碰判分目录、结果文件的标记）。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
CONFIGS = REPO / "experiments/configs"
REPORTS = Path("/root/work/reports/loop")
ARMS = {"base": "loop-r2-base.resolved.yaml", "v0-c04": "loop-r2-v0-c04.resolved.yaml"}
DATASETS = {   # 题集：（Harbor 的 datasets 段，每臂并发）。TB 有几道吃内存的题，并发压低
    "heldout": ([{"path": "/root/work/train/synth_split_v2/heldout"}], 10),
    "tb": (None, 6),
}


def jobs(tag: str) -> dict[tuple[str, str], str]:
    return {(ds, arm): f"loop-{tag}-{ds}-{arm}" for ds in DATASETS for arm in ARMS}


def cmd_write(a) -> None:
    tb = yaml.safe_load(open(CONFIGS / "qfinal-base-tb.resolved.yaml"))["datasets"]
    for (ds, arm), job in jobs(a.tag).items():
        cfg = copy.deepcopy(yaml.safe_load(open(CONFIGS / ARMS[arm])))
        datasets, conc = DATASETS[ds]
        cfg["job_name"] = job
        cfg["n_attempts"] = a.k
        cfg["orchestrator"]["n_concurrent_trials"] = conc
        cfg["datasets"] = copy.deepcopy(datasets if datasets is not None else tb)
        f = CONFIGS / f"{job}.resolved.yaml"
        if f.exists():
            sys.exit(f"{f} already exists")
        f.write_text(f"# 最终报告 {a.tag}（只报告、不做决定；D-095）：{arm} × {ds}，每题 {a.k} 次\n"
                     + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
        print(f"wrote {f.name}")
    print("bash tools/launch_job.sh " + " ".join(jobs(a.tag).values()))


def cmd_report(a) -> None:
    from agenteval.loop import accept as gate
    from tools.loop_cycle import concurrency, observe_jobs
    L = [f"# 最终报告 {a.tag}：v0 + append_nudge vs v0（只报告、不做决定）", "",
         "题目从没用来挑改动；两臂同时跑、同一个模型服务。区间是按题配对的 bootstrap 95% 区间。", ""]
    out = {}
    for ds in DATASETS:
        jb, jc = jobs(a.tag)[(ds, "base")], jobs(a.tag)[(ds, "v0-c04")]
        base, cand = observe_jobs([jb]), observe_jobs([jc])
        conc, info = concurrency([jb], [jc])
        d = gate.evaluate(base, cand, concurrent=conc, cfg=gate.GateConfig(min_attempts_per_task=2),
                          mechanism=("append_turns", "decrease"))
        n_int = (sum(1 for r in base if r.get("integrity_flag")), sum(1 for r in cand if r.get("integrity_flag")))
        n_cheat = (sum(1 for r in base if r.get("cheat_confirmed")), sum(1 for r in cand if r.get("cheat_confirmed")))
        out[ds] = {**d, "concurrency": info, "integrity_flags": n_int, "cheat_confirmed": n_cheat,
                   "n_trials": (len(base), len(cand)), "infra": (sum(1 for r in base if r.get("infra")), sum(1 for r in cand if r.get("infra")))}
        L += [f"## {ds}", "",
              f"- trial：v0 {len(base)}，v0+append_nudge {len(cand)}；机器故障 {out[ds]['infra']}；同时跑：{conc}",
              f"- 门的判断（仅供参考，不据此上线或回滚）：**{d['decision']}** — {d.get('reasons')}"]
        if d.get("pass"):
            p = d["pass"]
            L.append(f"- 通过率 {p['base']}% → {p['cand']}%，{p['delta']:+} pp [{p['ci'][0]:+}, {p['ci'][1]:+}]")
            for m, e in (d.get("efficiency") or {}).items():
                L.append(f"- {m}：{e['base']} → {e['cand']}（{100 * (e['rel'] or 0):+.0f}%，[{e['ci'][0]}, {e['ci'][1]}]）")
            if d.get("timeout"):
                t = d["timeout"]
                L.append(f"- 超时 {t['base']}% → {t['cand']}%，{t['delta']:+} pp [{t['ci'][0]:+}, {t['ci'][1]:+}]")
            if d.get("mechanism"):
                mm = d["mechanism"]
                L.append(f"- 机制（逐行追加轮数）：{mm['base']} → {mm['cand']}（{100 * (mm['rel'] or 0):+.0f}%）")
        L += [f"- 作弊巡查：可疑标记 {n_int}，碰诱饵 {n_cheat}" + ("（TB 判分没有加固，靠巡查）" if ds == "tb" else ""), ""]
    d_out = REPORTS / a.tag
    d_out.mkdir(parents=True, exist_ok=True)
    (d_out / "final.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    (d_out / "final.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(required=True)
    s = sub.add_parser("write"); s.add_argument("--tag", default="final"); s.add_argument("--k", type=int, default=4); s.set_defaults(fn=cmd_write)
    s = sub.add_parser("report"); s.add_argument("--tag", default="final"); s.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
