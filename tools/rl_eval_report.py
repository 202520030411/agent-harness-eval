"""D-072 最终评测报告：原版 / coderteach（SFT，D-071）/ RL（PSP 式 GRPO）三臂同时跑（D-040），留出合成题 37 × 3 + TB 30 × 4。
预注册（D-072，写于 RL 开跑前）：RL − 原版（留出题 M1）为 +5 到 +15 pp；RL 不低于 coderteach；RL 的 M3（失败 trial 里的假成功）低于 coderteach。
判定同 qeval_report：按题配对 bootstrap，区间不含 0 且 |Δ| ≥ 8 pp 才算有效。
用法（服务器）：PYTHONPATH=. .venv/bin/python tools/rl_eval_report.py --out /root/work/reports/rl_final
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
from pathlib import Path

from tools.qarm_report import paired_delta, pct
from tools.qeval_report import JOBS, NOISE_FLOOR_PP, arm_rows, arm_table, paired_rate_delta

ARMS = [("原版", "base"), ("coderteach（SFT）", "teach"), ("RL", "rl")]


def hint_transfer(history: list[dict]) -> list[tuple]:
    """提示依赖的检验（“提示留在上下文里训练”这条路的主要风险）：某题带规则做对过之后，下一次不带规则再做时还做得对吗。
    grpo.next_mode 让“带规则过了一半以上”的题下次去掉规则，所以这个对照是训练过程里自然产生的。返回 [(题, 带规则做对的步, 之后不带规则的步, 做对次数, 次数)]。"""
    won, out = {}, []
    for h in history:
        for t, (p, n) in h["passes_by_task"].items():
            if t in h["hinted"]:
                if p > 0:
                    won.setdefault(t, h["step"])
            elif t in won:
                out.append((t, won.pop(t), h["step"], p, n))
    return out


def main(a) -> None:
    L = ["# 最终评测：原版 vs SFT vs RL（Qwen3-Coder-30B-A3B，H2 harness，三臂同时跑）", "",
         "口径与预注册见 `tools/rl_eval_report.py` 顶部。", ""]
    for key, title in (("synth", "留出合成题（主评测）"), ("tb", "TB 30 题（迁移检查）")):
        data = {arm: arm_rows(arm, f"qfinal-{k}-{key}") for arm, k in ARMS if (JOBS / f"qfinal-{k}-{key}").exists()}
        if not data:
            continue
        for arm, rs in data.items():   # 基础设施报错不算能力（DESIGN 不变量 3）：开跑前就失败的（没轮次）剔除；其余列出来
            void = [r for r in rs if r["error"] in ("RuntimeError", "CancelledError") and r["turns"] == 0]
            other = collections.Counter(r["error"] for r in rs if r["error_kind"] == "infra" and r not in void)
            if void or other:
                L.append(f"**{arm}：{len(void)} 条开跑前就失败（已剔除）、其他基础设施报错 {dict(other)}——停 Pod 之前先 "
                         f"`bash tools/resume_jobs.sh <对应的 qfinal job>`，等 .done 后重跑本报告。**")
            data[arm] = [r for r in rs if r not in void]
        arm_table(data, title, L)
        L += ["| 比较（按题配对） | M1 Δ（pp） | 95% 区间 | 题数 | 判定 |", "|---|---|---|---|---|"]
        for x, y in (("原版", "RL"), ("coderteach（SFT）", "RL"), ("原版", "coderteach（SFT）")):
            if x in data and y in data:
                d, lo, hi, n = paired_delta(data[x], data[y])
                ok = (lo > 0 or hi < 0) and abs(d) >= NOISE_FLOOR_PP
                L.append(f"| {y} − {x} | {d:+.1f} | [{lo:+.1f}, {hi:+.1f}] | {n} | {'有效' if ok else '不显著'} |")
        if "RL" in data and "coderteach（SFT）" in data:
            fail = lambda r: not r["passed"]   # noqa: E731
            d, lo, hi, n = paired_rate_delta(data["coderteach（SFT）"], data["RL"], "false_success", fail)   # = RL − coderteach
            ok = hi < 0 and d <= -NOISE_FLOOR_PP                                                           # D-073 预测的方向：RL 更低
            L.append(f"\nM3 假成功（失败 trial，按题配对）：RL − coderteach {d:+.1f} pp [{lo:+.1f}, {hi:+.1f}]，{n} 题，"
                     f"{'预测成立' if ok else '不显著'}；原始比例 RL {pct(data['RL'], 'false_success', fail)}，"
                     f"SFT {pct(data['coderteach（SFT）'], 'false_success', fail)}（SFT 基线约 4%，8 pp 门槛几乎达不到，看区间）")
        L.append("")
    curve = subprocess.run(["python3", "tools/rl_status.py", a.rl_dir], capture_output=True, text=True).stdout
    L += ["## RL 训练过程（每步）", "", curve]
    sf = Path(a.rl_dir) / "state.json"
    if sf.exists():
        ev = hint_transfer(json.load(open(sf))["history"])
        ok = sum(1 for e in ev if e[3] > 0)
        hist = json.load(open(sf))["history"]
        pr = [(p, n) for h in hist for p, n in (h.get("probe_passes_by_task") or {}).values()]
        hr = [h["train"]["hint_reliance"]["mean"] for h in hist if (h.get("train") or {}).get("hint_reliance", {}).get("mean") is not None]
        L += ["## 去掉提示后还做得对吗（提示依赖检验，D-075）", "",
              f"- 每步给带提示的题另做的不带提示试做：{sum(p for p, _ in pr)}/{sum(n for _, n in pr)} 做对；同一批题带提示时的通过率见上表“带提示”一列。",
              f"- 提示依赖度（HiLL：带提示做对的轨迹，带提示与不带提示时每 token 平均 log-prob 之差；越接近 0 越不依赖提示）：各步均值 "
              + (", ".join(f"{x:.3f}" for x in hr) if hr else "—"),
              f"- 带规则做对过、之后又不带规则做过的题：{len(ev)} 道；不带规则时至少做对 1 次的：{ok} 道；"
              f"不带规则时的通过率 {sum(e[3] for e in ev)}/{sum(e[4] for e in ev)}。", ""]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "summary.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/root/work/reports/rl_final")
    ap.add_argument("--rl-dir", default="/root/work/rl")
    main(ap.parse_args())
