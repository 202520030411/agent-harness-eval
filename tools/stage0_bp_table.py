"""阶段 0：Qwen 的 bad pattern 表（TRAINING_PLAN §1.4）。

同一批 TB 2.1 干净题上对比三个模型：
  - 规则标签发生率（按 trial，失败标签；客观、免费）：Qwen / Seed / gpt-6-sol
  - 判官主因（仅 Qwen 失败）：gpt-6-sol v3、claude-sonnet-5 v3 各自分布 + 两家一致的“共识”
  - Seed 失败上的判官主因（若提供），用于“Seed 也有”的判定
  - 预注册的选目标标准逐条打勾；每类附代表轨迹
用法：PYTHONPATH=. .venv/bin/python tools/stage0_bp_table.py --out /root/work/reports/stage0/bp_table.md
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from agenteval.adapters.harbor import load_job
from agenteval.attribute.rules import label_trial

ROOT = Path(__file__).resolve().parent.parent
DELTA = 0.08


def clean_tasks() -> set[str]:
    return {t.strip() for t in (ROOT / "experiments/task_list_tb21_clean.txt").read_text().splitlines() if t.strip() and not t.startswith("#")}


def load(jobs: list[str], keep: set[str]):
    out = []
    for j in jobs:
        for t in load_job(Path(j)):
            if t.task_name in keep and t.status in ("ok", "agent_timeout"):
                out.append(label_trial(t))
    return out


VERIFY_RE = re.compile(r"(^|[;&|\s])(python3?|pytest|node|npm (test|run)|go (run|test)|cargo (run|test)|make|bash \S+\.sh|sh \S+\.sh|\./\S+"
                       r"|curl|diff|cmp|md5sum|sha256sum|sqlite3|git (log|status|diff|show)|cat \S+|ls -l|test -|\[ -)", re.I)


def verified_before_done(t, last: int = 3) -> bool:
    """宣布完成前的最后 last 轮里，是否执行过“运行成果 / 看输出 / 跑测试”一类的命令（启发式，三个模型同一口径）。"""
    steps = [s for s in t.agent_steps if s.keystrokes]
    tail = steps[-last - 1:-1] if len(steps) > last else steps[:-1]
    return any(VERIFY_RE.search(k) for s in tail for k in s.keystrokes)


_TIMEOUTS: dict[str, float] = {}


def timeout_of(t, root: str = "/root/.cache/harbor") -> float:
    """每道题 task.toml 里 [agent] timeout_sec；读不到按 900 s。"""
    if t.task_name not in _TIMEOUTS:
        from agenteval.adapters.tasks import task_index
        d = task_index(root).get(t.task_name)
        val = 900.0
        if d is not None and (d / "task.toml").exists():
            m = re.search(r"\[agent\][^\[]*?timeout_sec\s*=\s*([\d.]+)", (d / "task.toml").read_text(), re.S)
            if m:
                val = float(m.group(1))
        _TIMEOUTS[t.task_name] = val
    return _TIMEOUTS[t.task_name]


def rule_rates(trials) -> dict[str, float]:
    n = len(trials)
    c = collections.Counter()
    for t in trials:
        for name in {l.name for l in t.labels if l.source == "RULE" and l.kind == "failure"}:
            c[name] += 1
    return {k: v / n for k, v in c.items()} if n else {}


def read_judge(path: Path) -> dict[str, str]:
    """judge.jsonl → {trial_id: 主因}；文件不存在返回空。"""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["trial_id"]] = r["judge_primary"]
    return out


def main(a):
    keep = clean_tasks()
    qwen = load(a.qwen, keep); seed = load(a.seed, keep); strong = load(a.strong, keep)
    qf = [t for t in qwen if not t.passed]
    lines = ["# 阶段 0：Qwen3-Coder-30B-A3B 的 bad pattern 表（TB 2.1 干净题 30 道）", "",
             f"| 模型 | trial | 通过率 |", "|---|---|---|"]
    for name, ts in (("Qwen3-Coder-30B-A3B", qwen), ("Seed lite", seed), ("gpt-6-sol", strong)):
        lines.append(f"| {name} | {len(ts)} | {100 * sum(t.passed for t in ts) / max(1, len(ts)):.1f}% |")

    # 规则标签发生率（按 trial）
    rq, rs, rg = rule_rates(qwen), rule_rates(seed), rule_rates(strong)
    lines += ["", "## 1. 规则标签发生率（占全部 trial）", "",
              "| 标签 | Qwen | Seed | gpt-6-sol | Qwen − gpt-6-sol | 模型侧（≥ 8 pp） |", "|---|---|---|---|---|---|"]
    for k in sorted(set(rq) | set(rs) | set(rg), key=lambda k: -rq.get(k, 0)):
        d = rq.get(k, 0) - rg.get(k, 0)
        lines.append(f"| {k} | {100 * rq.get(k, 0):.0f}% | {100 * rs.get(k, 0):.0f}% | {100 * rg.get(k, 0):.0f}% | {100 * d:+.0f} | {'是' if d >= DELTA else ''} |")

    # 判官主因（Qwen 失败）
    jg, jc = read_judge(Path(a.judge_gpt)), read_judge(Path(a.judge_claude))
    ids = [t.trial_id for t in qf]
    cg = collections.Counter(jg.get(i, "MISSING") for i in ids)
    cc = collections.Counter(jc.get(i, "MISSING") for i in ids)
    cons = collections.Counter(jg[i] for i in ids if i in jg and i in jc and jg[i] == jc[i])
    n_cons = sum(cons.values())
    sj = {}
    if a.seed_judge_gpt and a.seed_judge_claude:
        sg, sc = read_judge(Path(a.seed_judge_gpt)), read_judge(Path(a.seed_judge_claude))
        sids = [t.trial_id for t in seed if not t.passed]
        sj = collections.Counter(sg[i] for i in sids if i in sg and i in sc and sg[i] == sc[i])
    lines += ["", f"## 2. 判官主因（Qwen 失败 {len(qf)} 条；两家一致 {n_cons} 条 = {100 * n_cons / max(1, len(qf)):.0f}%）", "",
              "| 主因 | gpt-6-sol 判 | claude 判 | 两家一致 | 占 Qwen 失败（一致） | Seed 失败上两家一致 |", "|---|---|---|---|---|---|"]
    for k in sorted(set(cg) | set(cc), key=lambda k: -(cg.get(k, 0) + cc.get(k, 0))):
        lines.append(f"| {k} | {cg.get(k, 0)} | {cc.get(k, 0)} | {cons.get(k, 0)} | {100 * cons.get(k, 0) / max(1, len(qf)):.0f}% | {sj.get(k, 0) if sj else '—'} |")

    # 代表轨迹（共识）
    lines += ["", "## 3. 代表轨迹（两家一致的主因）", ""]
    for k, _ in cons.most_common():
        ex = [i for i in ids if jg.get(i) == jc.get(i) == k][:5]
        lines.append(f"- **{k}**：" + "、".join(f"`{i}`" for i in ex))

    # 宣布完成前有没有真的运行 / 检查过（规则判定，三个模型同口径）+ 用掉了多少时限
    lines += ["", "## 4. 宣布完成前最后 3 轮有没有运行或检查（只看“宣布完成但没过”的 trial）", "",
              "| 模型 | 宣布完成但没过 | 其中最后 3 轮有运行 / 检查 | 用掉的时限（中位数） |", "|---|---|---|---|"]
    for name, ts in (("Qwen3-Coder-30B-A3B", qwen), ("Seed lite", seed), ("gpt-6-sol", strong)):
        pc = [t for t in ts if not t.passed and any(l.name == "PREMATURE_COMPLETION" for l in t.labels)]
        ver = sum(1 for t in pc if verified_before_done(t))
        frac = sorted((t.wall_clock_sec or 0) / timeout_of(t) for t in ts if t.wall_clock_sec)
        med = frac[len(frac) // 2] if frac else 0
        lines.append(f"| {name} | {len(pc)} | {ver} ({100 * ver / max(1, len(pc)):.0f}%) | {100 * med:.0f}% |")

    # 每道题的 Qwen 通过情况（看失败是否集中在少数题）
    per = collections.defaultdict(list)
    for t in qwen:
        per[t.task_name].append(t.passed)
    zero = sorted(k for k, v in per.items() if not any(v))
    lines += ["", f"## 5. 失败分布：Qwen 3 次全挂的题 {len(zero)} 道", "", "、".join(zero)]
    md = "\n".join(lines) + "\n"
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(md)
    print(md)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--qwen", nargs="+", default=["/root/work/jobs/stage0-qwen-coder30b-tb21clean"])
    ap.add_argument("--seed", nargs="+", default=["/root/work/jobs/h17-baseline", "/root/work/jobs/e4p-baseline"])
    ap.add_argument("--strong", nargs="+", default=["/root/work/jobs/e2-baseline-strong", "/root/work/jobs/e4s-baseline"])
    ap.add_argument("--judge-gpt", default="/root/work/reports/stage0/judge-gpt/judge.jsonl")
    ap.add_argument("--judge-claude", default="/root/work/reports/stage0/judge-claude/judge.jsonl")
    ap.add_argument("--seed-judge-gpt"); ap.add_argument("--seed-judge-claude")
    ap.add_argument("--out", default="/root/work/reports/stage0/bp_table.md")
    main(ap.parse_args())
