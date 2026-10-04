"""Qwen 四臂实验（docs/QWEN_PLAN.md §2–§3）的结果表与归责表。

读 /root/work/jobs/qarm-{h0-baseline,h1-interface,h2-gate,h3-qwencode}，每个 trial 一行，规则与阶段 0 同一口径：
  格式错误轮     观察里有 “Previous response had parsing errors”（tools/stage0_patterns.PARSE_ERR）；H3 是原生工具调用，没有这一层
  json_loop_end  最后 3 个 agent 步全是格式错误
  cnf            任一观察里出现 “command not found” / “sh: N: X: not found”（不依赖输出格式）
  echo_theater   最后 5 个 agent 步里用 echo 打印 ✓ / complete / success …（stage0_patterns.THEATER）
  false_success  失败、宣布了完成、最后 3 个 agent 步的文字里有承认没做成的措辞（stage0_patterns.ADMIT）；H3 每次都以最终回复结束，视为宣布完成
通过率按题配对：每题 2 次取平均，Δ = 各题差值的平均，95% 区间来自对题目的 bootstrap（10000 次）。
用法（服务器）：PYTHONPATH=. .venv/bin/python tools/qarm_report.py --out /root/work/reports/qarm
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
from pathlib import Path

from tools.stage0_patterns import ADMIT, PARSE_ERR, THEATER

JOBS = Path("/root/work/jobs")
ARMS = [("H0", "qarm-h0-baseline"), ("H1", "qarm-h1-interface"), ("H2", "qarm-h2-gate"), ("H3", "qarm-h3-qwencode")]
# 不依赖输出格式：Terminus 的终端画面是 “bash: ps: command not found”，`bash -c` 是 “bash: line 1: ps: …”，qwen-code 还会在前面加 “Output: ”，
# dash 是 “sh: 1: ps: not found”。2026-09-27 修：旧写法只认行首的第一种，H3 与 bash -c 的情况都漏数（H3 被误算成 0%）。
CNF_RE = re.compile(r"command not found|\bsh: \d+: [\w.+-]+: not found")
# 阶段 0 里 Qwen 3 次全挂的 17 道（QWEN_PLAN §4.5）
ALLFAIL_A = ["overfull-hbox", "tune-mjcf", "path-tracing-reverse", "mteb-retrieve", "vulnerable-secret", "large-scale-text-editing",
             "merge-diff-arc-agi-task", "llm-inference-batching-scheduler", "sqlite-db-truncate"]
ALLFAIL_B = ["regex-log", "kv-store-grpc", "code-from-image", "polyglot-c-py", "cobol-modernization", "gcode-to-text", "query-optimize",
             "chess-best-move"]
NOISE_FLOOR_PP = 8.0   # E1n：同配置两次重跑差 8 pp（README）


def _agent_steps(t: dict) -> list[dict]:
    return [s for s in t.get("steps", []) if s.get("source") == "agent"]


def _obs(s: dict) -> str:
    return "\n".join(str(r.get("content") or "") for r in ((s.get("observation") or {}).get("results") or []))


def _shell_cmds(s: dict) -> list[str]:
    """一步里执行的 shell 命令：Terminus 是 bash_command 的 keystrokes，qwen-code 是 run_shell_command 的 command。"""
    out = []
    for tc in s.get("tool_calls") or []:
        a = tc.get("arguments") or {}
        if tc.get("function_name") == "bash_command":
            out.append(a.get("keystrokes", ""))
        elif tc.get("function_name") == "run_shell_command":
            out.append(str(a.get("command", "")) + "\n")
    return out


def trial_row(arm: str, d: Path) -> dict | None:
    try:
        r = json.load(open(d / "result.json"))
    except Exception:  # noqa: BLE001
        return None
    task = r["task_name"].split("/")[-1]
    rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    exc = (r.get("exception_info") or {}).get("exception_type")
    # 异常分三类：timeout = 模型用完了时限；loop_guard = qwen-code 自带的防死循环机制终止（连续相同工具调用）；
    # 这两类都是正常的失败结果，判分照常。其余才算基础设施故障（infra），要单独核对。
    kind = None
    if exc == "AgentTimeoutError":
        kind = "timeout"
    elif exc == "NonZeroAgentExitCodeError" and (d / "agent" / "qwen-code.txt").exists() \
            and "Loop detection halted the run" in (d / "agent" / "qwen-code.txt").read_text(errors="ignore"):
        kind = "loop_guard"
    elif exc == "VerifierTimeoutError":   # 判分脚本本身跑超时（如交的 SQL 太慢）；按失败算，单列，因为机器负载也可能是原因
        kind = "verifier_timeout"
    elif exc:
        kind = "infra"
    ar = r.get("agent_result") or {}
    md = ar.get("metadata") or {}
    patched = md.get("patched") or {}
    try:
        t = json.load(open(d / "agent" / "trajectory.json"))
    except Exception:  # noqa: BLE001
        t = {"steps": []}
    steps = _agent_steps(t)
    obs = [_obs(s) for s in steps]
    msgs = [s.get("message") or "" for s in steps]
    keys = [_shell_cmds(s) for s in steps]
    passed = bool(rew is not None and rew >= 1)
    if arm == "H3":
        declared = bool(steps)                     # qwen-code 以最终回复结束
        n_parse = 0
        loop_end = False
    else:
        declared = "task_complete" in json.dumps(t.get("steps", [])[-3:]) or any("mark the task as complete" in o for o in obs[-3:])
        n_parse = sum(1 for o in obs if PARSE_ERR.search(o))
        loop_end = len(obs) >= 3 and all(PARSE_ERR.search(o) for o in obs[-3:])
    ae = r.get("agent_execution") or {}
    minutes = None
    if ae.get("started_at") and ae.get("finished_at"):
        from datetime import datetime
        minutes = (datetime.fromisoformat(ae["finished_at"].replace("Z", "+00:00"))
                   - datetime.fromisoformat(ae["started_at"].replace("Z", "+00:00"))).total_seconds() / 60
    gate = patched.get("completion_gate") or []
    return {
        "arm": arm, "task": task, "trial": d.name, "passed": passed, "reward": rew, "error": exc, "error_kind": kind,
        "turns": len(steps), "minutes": minutes,
        "tokens_out": ar.get("n_output_tokens"), "tokens_in": ar.get("n_input_tokens"),
        "n_parse_err": n_parse, "json_loop_end": loop_end,
        "cnf": any(CNF_RE.search(o) for o in obs),
        "echo_theater": any(THEATER.search(k) for ks in keys[-5:] for k in ks),
        "false_success": (not passed) and declared and any(ADMIT.search(m) for m in msgs[-3:]),
        "declared": declared,
        "gate_fired": bool(gate), "gate_reasons": [x for g in gate for x in g.get("reasons", [])],
        "parse_fixes": patched.get("parse_fixes") or {}, "continuation_notes": patched.get("continuation_notes") or 0,
    }


def load(arm: str, job: str, batch: str = "") -> list[dict]:
    rows = [row for d in sorted((JOBS / job).glob("*__*/")) if (row := trial_row(arm, d)) is not None]
    for r in rows:
        r["batch"] = batch
    return rows


def by_task(rows: list[dict]) -> dict[str, float]:
    acc = collections.defaultdict(list)
    for r in rows:
        acc[r["task"]].append(1.0 if r["passed"] else 0.0)
    return {t: sum(v) / len(v) for t, v in acc.items()}


def paired_delta(a: list[dict], b: list[dict], n_boot: int = 10000, seed: int = 0) -> tuple[float, float, float, int]:
    """b 相对 a 的通过率差（pp），按题配对；只用两边都有结果的题。返回 (Δ, 下界, 上界, 题数)。"""
    ta, tb = by_task(a), by_task(b)
    tasks = sorted(set(ta) & set(tb))
    diffs = [tb[t] - ta[t] for t in tasks]
    if not diffs:
        return float("nan"), float("nan"), float("nan"), 0
    rng = random.Random(seed)
    boots = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n_boot))
    return 100 * sum(diffs) / len(diffs), 100 * boots[int(0.025 * n_boot)], 100 * boots[int(0.975 * n_boot) - 1], len(tasks)


def pct(rows: list[dict], key: str, among=None) -> str:
    base = [r for r in rows if among is None or among(r)]
    k = sum(1 for r in base if r[key])
    return f"{k}/{len(base)} ({100 * k / max(1, len(base)):.0f}%)"


def mean(xs) -> float:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def main(a) -> None:
    prefixes = [x for x in a.prefixes.split(",") if x]
    data = {arm: [r for pf in prefixes for r in load(arm, job.replace("qarm-", f"{pf}-"), pf)] for arm, job in ARMS}
    L = [f"# Qwen 四臂实验：结果与归责（TB 2.1 干净 30 题，批次 {' + '.join(prefixes)}，Qwen3-Coder-30B-A3B，自己的 vLLM）", "",
         "口径见 `tools/qarm_report.py` 顶部；预注册见 `docs/QWEN_PLAN.md` §2 与 D-057；噪声底 8 pp（E1n，Seed），Qwen 自己的见第 7 节。", "",
         "## 1. 通过率", "", "| 臂 | trial 数 | agent 超时 / 防死循环终止 / 判分超时 / 基础设施故障 | 通过率（trial） | 按题 pass@2 | 平均轮数 | 平均 agent 分钟 | 平均输出 token |",
         "|---|---|---|---|---|---|---|---|"]
    for arm, rows in data.items():
        bt = collections.defaultdict(list)
        for r in rows:
            bt[r["task"]].append(r["passed"])
        at2 = sum(1 for v in bt.values() if any(v))
        ek = collections.Counter(r["error_kind"] for r in rows)
        L.append(f"| {arm} | {len(rows)} | {ek['timeout']} / {ek['loop_guard']} / {ek['verifier_timeout']} / {ek['infra']} | {pct(rows, 'passed')} | {at2}/{len(bt)} | "
                 f"{mean(r['turns'] for r in rows):.1f} | {mean(r['minutes'] for r in rows):.1f} | {mean(r['tokens_out'] for r in rows):.0f} |")
    L += ["", "## 2. 按题配对的差（pp，95% bootstrap 区间；判定：区间不含 0 且 |Δ| ≥ 8 pp）", "", "| 比较 | Δ | 区间 | 题数 | 判定 |", "|---|---|---|---|---|"]
    for x, y in (("H0", "H1"), ("H0", "H2"), ("H1", "H2"), ("H0", "H3")):
        d, lo, hi, n = paired_delta(data[x], data[y])
        verdict = "有效" if (lo > 0 or hi < 0) and abs(d) >= NOISE_FLOOR_PP else "不显著"
        L.append(f"| {y} − {x} | {d:+.1f} | [{lo:+.1f}, {hi:+.1f}] | {n} | {verdict} |")

    L += ["", "## 3. 毛病的发生率（同阶段 0 的规则）", "", "| 指标 | " + " | ".join(data) + " |", "|---|" + "---|" * len(data)]
    rows_spec = [
        ("出现过格式错误（全部 trial）", lambda rs: pct([dict(r, x=r["n_parse_err"] > 0) for r in rs], "x")),
        ("平均格式错误轮数 / trial", lambda rs: f"{mean(r['n_parse_err'] for r in rs):.2f}"),
        ("最后 3 步全是格式错误（卡死）", lambda rs: pct(rs, "json_loop_end")),
        ("出现过 command not found（全部 trial）", lambda rs: pct(rs, "cnf")),
        ("用 echo 打印代替检查（全部 trial）", lambda rs: pct(rs, "echo_theater")),
        ("用 echo 打印代替检查（失败 trial）", lambda rs: pct(rs, "echo_theater", lambda r: not r["passed"])),
        ("明知没做成仍宣布完成（失败 trial）", lambda rs: pct(rs, "false_success", lambda r: not r["passed"])),
    ]
    for label, f in rows_spec:
        L.append(f"| {label} | " + " | ".join(f(rs) for rs in data.values()) + " |")
    L.append("\nH3 是原生工具调用，没有“格式错误”这一层（记 0）；H3 的 echo / 假成功按它的 shell 命令和最终回复计，与 Terminus 臂的可比性较弱。")

    L += ["", "## 4. 两个 harness 改动各自做了什么", ""]
    for arm in ("H1", "H2"):
        fx = collections.Counter()
        for r in data[arm]:
            fx.update(r["parse_fixes"])
        L.append(f"- {arm} 宽松解析救回的轮次：{dict(fx) or '无'}；续行提示 {sum(r['continuation_notes'] for r in data[arm])} 次")
    g = [r for r in data["H2"] if r["gate_fired"]]
    reasons = collections.Counter(x for r in g for x in r["gate_reasons"])
    L.append(f"- H2 交卷把关打回 {len(g)}/{len(data['H2'])} 个 trial（{dict(reasons)}）；被打回的里最终通过 {sum(r['passed'] for r in g)} 个"
             f"（{', '.join(r['trial'] for r in g if r['passed']) or '无'}）")

    L += ["", "## 5. 阶段 0 三次全挂的 17 道题：每臂有几道至少过一次（2 次里）", "", "| 类 | 题数 | " + " | ".join(data) + " |",
          "|---|---|" + "---|" * len(data)]
    for label, tasks in (("A 毛病拖垮", ALLFAIL_A), ("B 技能缺口", ALLFAIL_B)):
        cells = []
        for rs in data.values():
            ok = sorted({r["task"] for r in rs if r["task"] in tasks and r["passed"]})
            cells.append(f"{len(ok)}" + (f"（{', '.join(ok)}）" if ok else ""))
        L.append(f"| {label} | {len(tasks)} | " + " | ".join(cells) + " |")

    L += ["", "## 6. 逐题（每臂 2 次里通过几次）", "", "| 题 | " + " | ".join(data) + " |", "|---|" + "---|" * len(data)]
    tasks = sorted({r["task"] for rs in data.values() for r in rs})
    for t in tasks:
        cells = []
        for rs in data.values():
            v = [r for r in rs if r["task"] == t]
            cells.append(f"{sum(r['passed'] for r in v)}/{len(v)}" + ("!" if any(r["error_kind"] == "infra" for r in v) else ""))
        L.append(f"| {t} | " + " | ".join(cells) + " |")
    L.append("\n“!” = 该题有 trial 出了基础设施故障（不含超时与 qwen-code 防死循环终止），需单独核对。")

    if len(prefixes) >= 2:
        L += ["", f"## 7. 同一个臂两批之间的差（{prefixes[1]} − {prefixes[0]}，同配置重跑 = 噪声估计）", "",
              "| 臂 | 第一批通过率 | 第二批通过率 | Δ（pp） | 区间 |", "|---|---|---|---|---|"]
        for arm, rs in data.items():
            b1 = [r for r in rs if r["batch"] == prefixes[0]]
            b2 = [r for r in rs if r["batch"] == prefixes[1]]
            d, lo, hi, n = paired_delta(b1, b2)
            L.append(f"| {arm} | {pct(b1, 'passed')} | {pct(b2, 'passed')} | {d:+.1f} | [{lo:+.1f}, {hi:+.1f}] |")
        L += ["", "### 第一批单独的配对差（D-057：照报）", "", "| 比较 | Δ | 区间 |", "|---|---|---|"]
        for x, y in (("H0", "H1"), ("H0", "H2"), ("H1", "H2"), ("H0", "H3")):
            d, lo, hi, n = paired_delta([r for r in data[x] if r["batch"] == prefixes[0]], [r for r in data[y] if r["batch"] == prefixes[0]])
            L.append(f"| {y} − {x} | {d:+.1f} | [{lo:+.1f}, {hi:+.1f}] |")

    # 8. 归责表（QWEN_PLAN §3）。“最好 harness”= H1/H2/H3 里合并通过率最高的臂（2026-09-27 开跑后、看到结论前定的规则）；
    # gpt-6-sol 的对照用阶段 0 它在同样 30 题上的 Terminus 轨迹，按本脚本同一套规则重算。
    clean = {t.strip() for t in open(Path(__file__).resolve().parent.parent / "experiments/task_list_tb21_clean.txt")
             if t.strip() and not t.startswith("#")}
    ref = [r for job in a.ref_jobs.split(",") if job for r in load("gpt", job) if r["task"] in clean]
    rate = lambda rs, key, among=None: (lambda b: 100 * sum(1 for r in b if r[key]) / max(1, len(b)))([r for r in rs if among is None or among(r)])
    pr = {k: sum(r["passed"] for r in data[k]) / max(1, len(data[k])) for k in ("H1", "H2", "H3")}
    bests = [k for k in ("H1", "H2", "H3") if pr[k] == max(pr.values())]   # 平票就每个并列的臂各出一张表（D-059）
    failed = lambda r: not r["passed"]
    for r in ref + [r for k in ["H0"] + bests for r in data[k]]:
        r["_fmt"] = r["n_parse_err"] > 0
    bps = [("格式错误（出现过，全部 trial）", "_fmt", None), ("卡死在格式错误里（全部 trial）", "json_loop_end", None),
           ("命令不存在（全部 trial）", "cnf", None), ("用 echo 代替检查（失败 trial）", "echo_theater", failed),
           ("明知没做成仍宣布完成（失败 trial）", "false_success", failed)]
    tie = f"（平票：{' = '.join(bests)}，每个各出一张表；见 D-059）" if len(bests) > 1 else ""
    L += ["", f"## 8. 归责表（最好 harness = H1/H2/H3 里合并通过率最高的臂{tie}）", "",
          f"gpt-6-sol 对照：阶段 0 同样 30 题上的 {len(ref)} 个 trial（{a.ref_jobs}），同一套规则；"
          f"它的失败 trial 只有 {sum(1 for r in ref if not r['passed'])} 个，“失败 trial”那两行的对照数不可靠。"]
    for best in bests:
        L += ["", f"### 最好 harness = {best}", "",
              "| 毛病 | H0 | 最好 harness | harness 修掉 | 残余 − gpt-6-sol | 交给训练？（残余比 gpt 高 ≥ 8 pp） |", "|---|---|---|---|---|---|"]
        for label, key, among in bps:
            h0, hb, g = rate(data["H0"], key, among), rate(data[best], key, among), rate(ref, key, among)
            removed = f"{100 * (h0 - hb) / h0:.0f}%" if h0 > 0 else "—"
            L.append(f"| {label} | {h0:.0f}% | {hb:.0f}% | {removed} | {hb - g:+.0f} pp（gpt {g:.0f}%） | {'是' if hb - g >= 8 else '否'} |")
    L.append("\n失败 trial 的比例以各臂自己的失败 trial 为分母（harness 改变了失败的构成，比例要与通过率一起看）。")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.md").write_text("\n".join(L) + "\n")
    with open(out / "trials.jsonl", "w") as f:
        for rs in data.values():
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/root/work/reports/qarm")
    ap.add_argument("--prefixes", default="qarm,qarm2", help="要合并的批次（逗号分隔）；qsmoke = 用冒烟数据检查脚本本身")
    ap.add_argument("--ref-jobs", default="e2-baseline-strong,e4s-baseline", help="gpt-6-sol 的阶段 0 对照 job（逗号分隔）")
    main(ap.parse_args())
