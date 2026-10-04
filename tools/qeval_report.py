"""训练前后对比与消融（QWEN_PLAN §4.1、D-063、D-064、D-067）的报告。

留出合成题：原版 / coderplain（第一轮）/ coderlora（+ 第二轮通用提示）/ coderskill（+ 第三轮技能提示）四臂；TB 30 题：原版 / coderlora / coderskill。
指标（预注册）：
  M1 通过率（按题配对 bootstrap；判定：区间不含 0 且 ≥ 8 pp）
  M2 第一次宣布完成时“最后一次改文件后没再运行过任何东西”的比例（分母 = 宣布过完成的 trial；与 H2 把关同一个函数）
  M3 失败 trial 里“明知没做成仍宣布完成”的比例（阶段 0 同一规则）
拆分（描述性）：按技能族、按难度档（该题在原版臂 3 次里过 0 / 1–2 / 3 次）。另：Seed 排序检验（D-064）、复杂度对照（每 trial 轮数、输出 token）、训练数据构成。
用法（服务器）：PYTHONPATH=. .venv/bin/python tools/qeval_report.py --out /root/work/reports/qeval
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from terminus2_patches.helpers import no_run_after_last_write
from tools.qarm_report import load, mean, paired_delta, pct

JOBS = Path("/root/work/jobs")
SYNTH = [("原版", "qeval-base-synth"), ("coderplain", "qeval-plain-synth"), ("coderlora", "qeval-lora-synth"), ("coderskill", "qeval-skill-synth"),
         ("coderteach", "qeval-teach-synth")]
TB = [("原版", "qeval-base-tb"), ("coderlora", "qeval-lora-tb"), ("coderskill", "qeval-skill-tb"), ("coderteach", "qeval-teach-tb")]
TWO_BY_TWO = ("coderteach", "qeval-teach-synth-h0")   # D-069：2×2 用最终模型 coderteach（D-068 原来用 coderskill）
NOISE_FLOOR_PP = 8.0


def claim_m2(d: Path) -> bool | None:
    """第一次宣布完成时没有运行证据 → True；运行过 → False；从没宣布完成 → None。"""
    try:
        t = json.load(open(d / "agent" / "trajectory.json"))
    except Exception:  # noqa: BLE001
        return None
    executed = []
    for s in t.get("steps", []):
        if s.get("source") != "agent":
            continue
        calls = s.get("tool_calls") or []
        executed += [(c.get("arguments") or {}).get("keystrokes", "") for c in calls if c.get("function_name") == "bash_command"]
        if any(c.get("function_name") == "mark_task_complete" for c in calls):
            return no_run_after_last_write(executed)
    return None


HINT_WORDS = re.compile(r"\b(reviewer|hints?|notes from)\b", re.I)


def mentions_hint(d: Path) -> bool:
    """D-071 承诺的检查：训练数据里保留了 Reviewer note / 规则，评测时没有任何提示——模型的回复里还“提起”reviewer / hint 吗？"""
    try:
        t = json.load(open(d / "agent" / "trajectory.json"))
    except Exception:  # noqa: BLE001
        return False
    return any(HINT_WORDS.search(s.get("message") or "") for s in t.get("steps", []) if s.get("source") == "agent")


def arm_rows(label: str, job: str) -> list[dict]:
    rows = load(label, job)
    for r in rows:
        r["family"] = r["task"].split("--")[0]
        r["m2"] = claim_m2(JOBS / job / r["trial"])
        r["mentions_hint"] = mentions_hint(JOBS / job / r["trial"])
    return rows


def m2_rate(rows) -> str:
    c = [r for r in rows if r["m2"] is not None]
    k = sum(1 for r in c if r["m2"])
    return f"{k}/{len(c)} ({100 * k / max(1, len(c)):.0f}%)"


def paired_rate_delta(a: list[dict], b: list[dict], key: str, among, n_boot: int = 10000, seed: int = 0):
    """M2 / M3 这类“在某个子集里的比例”的按题配对差（pp）：每题先算该臂在子集里的比例，只用两臂在这道题上都有子集样本的题，对题 bootstrap。
    （QWEN_PLAN §4.1 预注册：M2、M3 报点估计与按题 bootstrap 区间。）"""
    import random

    def per_task(rows):
        acc = collections.defaultdict(list)
        for r in rows:
            if among(r):
                acc[r["task"]].append(1.0 if r[key] else 0.0)
        return {t: sum(v) / len(v) for t, v in acc.items()}
    ta, tb = per_task(a), per_task(b)
    tasks = sorted(set(ta) & set(tb))
    diffs = [tb[t] - ta[t] for t in tasks]
    if not diffs:
        return float("nan"), float("nan"), float("nan"), 0
    rng = random.Random(seed)
    boots = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n_boot))
    return 100 * sum(diffs) / len(diffs), 100 * boots[int(0.025 * n_boot)], 100 * boots[int(0.975 * n_boot) - 1], len(tasks)


def arm_table(data: dict, title: str, L: list) -> None:
    L += [f"### {title}", "", "| 臂 | trial | M1 通过率 | M2 没检查就交卷（宣布过完成的 trial） | M3 假成功（失败 trial） | 出现过格式错误 | 超时 | 回复里提到 reviewer / 提示 | 平均轮数 | 平均输出 token |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for arm, rs in data.items():
        L.append(f"| {arm} | {len(rs)} | {pct(rs, 'passed')} | {m2_rate(rs)} | {pct(rs, 'false_success', lambda r: not r['passed'])} | "
                 f"{pct([dict(r, x=r['n_parse_err'] > 0) for r in rs], 'x')} | {pct([dict(r, x=r['error_kind'] == 'timeout') for r in rs], 'x')} | {pct(rs, 'mentions_hint')} | {mean(r['turns'] for r in rs):.1f} | {mean(r['tokens_out'] for r in rs):.0f} |")
    L.append("")


def main(a) -> None:
    L = ["# 训练前后对比与消融（Qwen3-Coder-30B-A3B，LoRA SFT on 自己的轨迹；H2 harness）", "",
         "口径：`tools/qeval_report.py` 顶部；预注册：QWEN_PLAN §4.1、D-063、D-064、D-067。", ""]
    synth = {arm: arm_rows(arm, job) for arm, job in SYNTH if (JOBS / job).exists()}
    tb = {arm: arm_rows(arm, job) for arm, job in TB if (JOBS / job).exists()}

    L += ["## 1. 留出合成题（主评测）", ""]
    arm_table(synth, "三臂", L)
    L += ["| 比较（按题配对） | M1 Δ（pp） | 95% 区间 | 题数 | 判定 |", "|---|---|---|---|---|"]
    for x, y in (("原版", "coderplain"), ("原版", "coderlora"), ("原版", "coderskill"), ("原版", "coderteach"),
                 ("coderplain", "coderlora"), ("coderlora", "coderskill"), ("coderlora", "coderteach"), ("coderskill", "coderteach")):
        if x in synth and y in synth:
            d, lo, hi, n = paired_delta(synth[x], synth[y])
            ok = (lo > 0 or hi < 0) and abs(d) >= NOISE_FLOOR_PP
            L.append(f"| {y} − {x} | {d:+.1f} | [{lo:+.1f}, {hi:+.1f}] | {n} | {'有效' if ok else '不显著'} |")
    L.append("")
    if "原版" in synth:
        L += ["| 比较（按题配对） | M2 Δ（pp，越负越好） | 95% 区间 | 题数 | M3 Δ（pp，越负越好） | 95% 区间 | 题数 |", "|---|---|---|---|---|---|---|"]
        for y in [x for x in synth if x != "原版"]:
            d2, lo2, hi2, n2 = paired_rate_delta(synth["原版"], synth[y], "m2", lambda r: r["m2"] is not None)
            d3, lo3, hi3, n3 = paired_rate_delta(synth["原版"], synth[y], "false_success", lambda r: not r["passed"])
            L.append(f"| {y} − 原版 | {d2:+.1f} | [{lo2:+.1f}, {hi2:+.1f}] | {n2} | {d3:+.1f} | [{lo3:+.1f}, {hi3:+.1f}] | {n3} |")
        L.append("")

    if "原版" in synth:
        base_by_task = collections.defaultdict(list)
        for r in synth["原版"]:
            base_by_task[r["task"]].append(r["passed"])
        tier = {t: ("0/3" if sum(v) == 0 else "3/3" if sum(v) == len(v) else "1–2/3") for t, v in base_by_task.items()}
        L += ["## 2. 拆分（描述性）", "", "### 按难度档（原版在该题 3 次里过几次）", "",
              "| 档 | 题数 | " + " | ".join(synth) + " |", "|---|---|" + "---|" * len(synth)]
        for tr in ("0/3", "1–2/3", "3/3"):
            ts = {t for t, v in tier.items() if v == tr}
            L.append(f"| {tr} | {len(ts)} | " + " | ".join(pct([r for r in rs if r['task'] in ts], 'passed') for rs in synth.values()) + " |")
        fams = sorted({r["family"] for rs in synth.values() for r in rs})
        L += ["", "### 按技能族", "", "| 族 | " + " | ".join(synth) + " |", "|---|" + "---|" * len(synth)]
        for f in fams:
            L.append(f"| {f} | " + " | ".join(pct([r for r in rs if r['family'] == f], 'passed') for rs in synth.values()) + " |")
        L.append("")

    # 共同进化 2×2（D-068）：{原版, coderskill} × {H0, H2}，留出合成题
    tm = TWO_BY_TWO[0]
    cells = {("原版", "H2"): synth.get("原版"), (tm, "H2"): synth.get(tm)}
    for m, job in (("原版", "qeval-base-synth-h0"), TWO_BY_TWO):
        if (JOBS / job).exists():
            cells[(m, "H0")] = arm_rows(f"{m}×H0", job)
    if all(cells.get(k) for k in (("原版", "H0"), ("原版", "H2"), (tm, "H0"), (tm, "H2"))):
        L += ["## 2b. 共同进化 2×2（harness × 训练，D-068）", "", "| 格 | 通过率 | 出现过格式错误 | M2 没检查就交卷 |", "|---|---|---|---|"]
        for m in ("原版", tm):
            for h in ("H0", "H2"):
                rs = cells[(m, h)]
                L.append(f"| {m} × {h} | {pct(rs, 'passed')} | {pct([dict(r, x=r['n_parse_err'] > 0) for r in rs], 'x')} | {m2_rate(rs)} |")
        for m in ("原版", tm):
            d, lo, hi, n = paired_delta(cells[(m, "H0")], cells[(m, "H2")])
            L.append(f"\n{m}：H2 − H0 = {d:+.1f} pp [{lo:+.1f}, {hi:+.1f}]")
        # 交互项：按题算（skill_H2 − skill_H0）−（base_H2 − base_H0），对题 bootstrap
        import random
        from tools.qarm_report import by_task
        bt = {k: by_task(v) for k, v in cells.items()}
        tasks = sorted(set.intersection(*(set(v) for v in bt.values())))
        diffs = [(bt[(tm, "H2")][t] - bt[(tm, "H0")][t]) - (bt[("原版", "H2")][t] - bt[("原版", "H0")][t]) for t in tasks]
        rng = random.Random(0)
        boots = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(10000))
        L += [f"\n交互项（{tm} 的 H2−H0 减 原版的 H2−H0）：{100 * sum(diffs) / len(diffs):+.1f} pp "
              f"[{100 * boots[250]:+.1f}, {100 * boots[9749]:+.1f}]（{len(tasks)} 题）。负 = 训练后补丁作用变小（模型吸收了）；正 = 训练后更依赖补丁。", ""]

    L += ["## 3. TB 30 题（迁移检查）", ""]
    arm_table(tb, "两臂", L)
    for arm in ("coderlora", "coderskill", "coderteach"):
        if "原版" in tb and arm in tb:
            d, lo, hi, n = paired_delta(tb["原版"], tb[arm])
            L += [f"{arm} − 原版：M1 {d:+.1f} pp [{lo:+.1f}, {hi:+.1f}]（{n} 题）"]
    L.append("")

    seed_job = JOBS / "qcheck-seed-synth-heldout"
    if seed_job.exists():
        seed = arm_rows("Seed lite", "qcheck-seed-synth-heldout")
        L += ["## 4. 强弱模型排序一致性（D-064）", "", "| 集合 | Seed lite | 原版 Qwen | 差 |", "|---|---|---|---|"]
        if "原版" in synth:
            ps = sum(r["passed"] for r in seed) / max(1, len(seed)); pq = sum(r["passed"] for r in synth["原版"]) / max(1, len(synth["原版"]))
            L.append(f"| 留出合成题（都用 H2） | {pct(seed, 'passed')} | {pct(synth['原版'], 'passed')} | {100 * (ps - pq):+.0f} pp |")
        L += ["| TB 30 题（都用 H0，阶段 0 / 四臂实验） | 146/180 (81%) | 19/120 (16%) | +65 pp |", ""]
        gpt_job = JOBS / "qcheck-gpt-synth-heldout"
        if gpt_job.exists():
            gpt = arm_rows("gpt-6-sol", "qcheck-gpt-synth-heldout")
            L += ["| 模型 | 留出合成题（H2） | TB 30 题（H0） |", "|---|---|---|",
                  f"| 原版 Qwen | {pct(synth['原版'], 'passed') if '原版' in synth else '—'} | 19/120 (16%) |",
                  f"| Seed lite | {pct(seed, 'passed')} | 146/180 (81%) |",
                  f"| gpt-6-sol | {pct(gpt, 'passed')} | 58/64 (91%) |", ""]

    if "原版" in synth and "原版" in tb:
        L += ["## 5. 复杂度对照（原版 Qwen）", "", "| 集合 | 平均轮数 | 平均输出 token / trial | 通过率 |", "|---|---|---|---|",
              f"| 留出合成题 | {mean(r['turns'] for r in synth['原版']):.1f} | {mean(r['tokens_out'] for r in synth['原版']):.0f} | {pct(synth['原版'], 'passed')} |",
              f"| TB 30 题 | {mean(r['turns'] for r in tb['原版']):.1f} | {mean(r['tokens_out'] for r in tb['原版']):.0f} | {pct(tb['原版'], 'passed')} |", ""]

    if a.sft_meta and Path(a.sft_meta).exists():
        L += ["## 6. 训练数据构成", "", Path(a.sft_meta).read_text(), ""]

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "summary.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/root/work/reports/qeval")
    ap.add_argument("--sft-meta", default="/root/work/train/sft_meta.md", help="训练数据构成（导出时写）")
    main(ap.parse_args())
