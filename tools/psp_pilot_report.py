"""D-072 试点报告：同一批 51 道难题（前两轮 6 次全挂）上三种提示的对比，决定 RL 里难题用哪种提示。
  D-067 开头技能提示（没看失败记录）   qroll-h2-synth-train-skill   51 × 3
  A  PSP 式开头规则（看过失败记录）     qpilot-psp-rules             51 × 2
  B  D-069 实时 Teacher（做题中途插话）  qroll-h2-synth-train-teach   51 × 2
预注册的决定规则（D-072）：A 通过率 ≥ 15% → RL 用 A；否则用 B（B 的 API 另需用户批准）。
A 在与 B 相同的条件下跑（D-074）：只挂原版的 vLLM、并发 16、同时没有别的 job。
注意：这 51 题是按“前两轮 0 次做对”挑出来的，不带提示重跑也会因为运气做对几次（回归均值），所以三种提示的绝对通过率都偏高于“提示的真实作用”；
三者之间的比较是公平的（同一批题、同一模型、同一 harness，都在挑题之后跑）。
用法（服务器）：PYTHONPATH=. .venv/bin/python tools/psp_pilot_report.py --out /root/work/reports/psp_pilot
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from tools.qarm_report import JOBS, load, paired_delta, pct

ARMS = [("D-067 开头技能提示", "qroll-h2-synth-train-skill"), ("A PSP 式开头规则", None),     # A 的 job 由 --pilot-job 给
        ("B 实时 Teacher", "qroll-h2-synth-train-teach")]
THRESHOLD = 0.15
_COUNT = re.compile(r"(\d+) (passed|failed|errors?)\b")


def passed_share(d: Path) -> float | None:
    """隐藏测试里过了几成：读 pytest 最后一行汇总（“3 failed, 5 passed in 0.52s”）；setup error 算没过。"""
    f = d / "verifier" / "test-stdout.txt"
    if not f.exists():
        return None
    lines = [x for x in f.read_text(errors="ignore").splitlines() if _COUNT.search(x) and " in " in x]
    if not lines:
        return None
    c = collections.Counter()
    for n, k in _COUNT.findall(lines[-1]):
        c["passed" if k == "passed" else "failed"] += int(n)
    tot = c["passed"] + c["failed"]
    return c["passed"] / tot if tot else None


def main(a) -> None:
    data = {}
    for arm, job in ARMS:
        job = job or a.pilot_job
        if (JOBS / job).exists():
            rows = load(arm, job)
            for r in rows:
                r["passed_share"] = passed_share(JOBS / job / r["trial"])
            data[arm] = rows
    L = ["# 难题提示方式对比（D-072 试点）", "", "口径与决定规则见 `tools/psp_pilot_report.py` 顶部。", "",
         "| 方式 | trial | 通过 | 至少做对 1 次的题 | 隐藏测试平均通过比例 | 超时 | 基础设施报错 |", "|---|---|---|---|---|---|---|"]
    for arm, rs in data.items():
        tasks = collections.defaultdict(list)
        for r in rs:
            tasks[r["task"]].append(r["passed"])
        fr = [r["passed_share"] for r in rs if r["passed_share"] is not None]
        L.append(f"| {arm} | {len(rs)} | {pct(rs, 'passed')} | {sum(any(v) for v in tasks.values())}/{len(tasks)} | "
                 f"{100 * sum(fr) / max(1, len(fr)):.0f}%（{len(fr)} 个有结果） | {sum(r['error_kind'] == 'timeout' for r in rs)} | "
                 f"{sum(r['error_kind'] == 'infra' for r in rs)} |")
    L += ["", "| 比较（按题配对） | 通过率差（pp） | 95% 区间 | 题数 |", "|---|---|---|---|"]
    for x, y in (("D-067 开头技能提示", "A PSP 式开头规则"), ("B 实时 Teacher", "A PSP 式开头规则"), ("D-067 开头技能提示", "B 实时 Teacher")):
        if x in data and y in data:
            d, lo, hi, n = paired_delta(data[x], data[y])
            L.append(f"| {y} − {x} | {d:+.1f} | [{lo:+.1f}, {hi:+.1f}] | {n} |")
    rules_f = Path(a.rules)
    if rules_f.exists():
        recs = json.load(open(rules_f))
        L += ["", f"A 的规则：{sum(1 for r in recs if r['rules'])}/{len(recs)} 题有规则；丢掉的泄题规则 {sum(r['leaks_dropped'] for r in recs)} 条；"
              f"没有规则的题（照跑，算在 A 头上）：{[(r['task'], r['reason']) for r in recs if not r['rules']][:8]}"]
    a_rows = data.get("A PSP 式开头规则")
    if a_rows:
        rate = sum(r["passed"] for r in a_rows) / len(a_rows)
        choice = "A（PSP 式开头规则）" if rate >= THRESHOLD else "B（实时 Teacher，API 需另批）"
        L += ["", f"**决定（预注册规则）：A 通过率 {100 * rate:.0f}% {'≥' if rate >= THRESHOLD else '<'} {100 * THRESHOLD:.0f}% → RL 难题提示用 {choice}。**"]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "summary.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/root/work/reports/psp_pilot")
    ap.add_argument("--rules", default="/root/work/train/psp_rules.json")
    ap.add_argument("--pilot-job", default="qpilot-psp-rules2", help="第一次 qpilot-psp-rules 与评测同时跑、超时太多，已中止（D-074）")
    main(ap.parse_args())
