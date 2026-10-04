"""H17 开关的离线预检：只调首轮，不起容器。

首轮回复只依赖题面 + 初始终端画面（还没执行过任何命令），所以开关判定可以离线复现。
比较两种开关与 clarity ≥2 的 14 道模糊题的重合度：
  G1  首轮模板（tools/h17_pilot/g1_turn1_template.txt，契约 v1 + 每个模糊点自评 severity）任一条 ≥2 → 开契约
  G2  harness 开跑前单独调一次 Seed 做 clarity_v1 评分，任一维 ≥2 → 开契约（被 D-049 采用，实现见 Terminus2Patched._clarity_gate）
2026-09-26 第一次跑（G2 的 user 消息带题名）：G1 模糊 33/42、清晰 35/81；G2 模糊 34/42、清晰 21/81。
--g2-only 复跑与 agent 里完全相同的 G2 消息（不带题名），用来确认实跑时的开关行为。
用法（服务器）：source ~/.secrets.env; .venv/bin/python tools/h17_gate_pilot.py --k 3 --out /root/work/reports/h17/gate_pilot.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import glob
import json
import os
import re
import time
from pathlib import Path

import litellm

from terminus2_patches.agent import _clarity_score
from terminus2_patches.helpers import extract_json_fields

ROOT = Path(__file__).resolve().parent.parent
MODEL = "openai/doubao-seed-2-1-lite-260915"
API_BASE = "https://ark.cn-beijing.volces.com/api/v3"


def initial_prompts(job_dir: str) -> dict[str, tuple[str, str]]:
    """每道题取一条轨迹的首条 user 消息，拆出 (instruction, terminal_state)。"""
    out = {}
    for f in sorted(glob.glob(f"{job_dir}/*/agent/trajectory.json")):
        task = Path(f).parts[-3].split("__")[0]
        if task in out:
            continue
        msg = json.load(open(f))["steps"][0]["message"]
        head, _, rest = msg.partition("Task Description:\n")
        instruction, _, terminal = rest.rpartition("\n\nCurrent terminal state:\n")
        if head and instruction:
            out[task] = (instruction, terminal)
    return out


async def call(sem, messages, extra=None):
    async with sem:
        for attempt in range(3):
            try:
                t0 = time.time()
                r = await litellm.acompletion(model=MODEL, api_base=API_BASE, messages=messages,
                                              api_key=os.environ["ARK_API_KEY"], **(extra or {}))
                u = r.usage
                return r.choices[0].message.content or "", (u.prompt_tokens, u.completion_tokens), round(time.time() - t0, 1)
            except Exception:  # noqa: BLE001
                await asyncio.sleep(5 * (attempt + 1))
        return "", (0, 0), None


def decisive_ambiguities(ambiguities, min_severity: int = 2) -> list:
    """G1：首轮 ambiguities 里自评 severity ≥ min_severity 的条目；severity 缺失或不是 0–3 的数当 0。"""
    if not isinstance(ambiguities, list):
        return []
    out = []
    for a in ambiguities:
        m = re.search(r"[0-3]", str(a.get("severity", ""))) if isinstance(a, dict) else None
        if m and int(m.group(0)) >= min_severity:
            out.append(a)
    return out


async def main(a):
    template = (ROOT / "tools/h17_pilot/g1_turn1_template.txt").read_text()
    clarity_sys = (ROOT / "terminus2_patches/prompts/clarity_gate.txt").read_text()
    prompts = initial_prompts(a.source_job)
    tasks = [t.strip() for t in open(ROOT / "experiments/task_list.txt") if t.strip() and not t.startswith("#")]
    amb = {t.strip() for t in open(ROOT / "experiments/task_list_ambiguous.txt") if t.strip()}
    sem = asyncio.Semaphore(a.concurrency)
    jobs = []
    for t in tasks:
        if t not in prompts:
            print("no prompt:", t); continue
        ins, term = prompts[t]
        g1_msg = [{"role": "user", "content": template.format(instruction=ins, terminal_state=term)}]
        g2_msg = [{"role": "system", "content": clarity_sys},
                  {"role": "user", "content": f"INSTRUCTION:\n{ins.strip()}"}]  # 与 _clarity_gate 逐字一致
        for i in range(a.k):
            if not a.g2_only:
                jobs.append((t, "G1", i, call(sem, g1_msg)))
            jobs.append((t, "G2", i, call(sem, g2_msg, {"extra_body": {"thinking": {"type": "disabled"}}} if a.no_thinking else None)))
    results = await asyncio.gather(*(j[3] for j in jobs))
    rows = []
    for (t, gate, i, _), (raw, usage, latency) in zip(jobs, results):
        row = {"task": t, "gate": gate, "rep": i, "ambiguous_14": t in amb, "usage": usage, "latency_sec": latency}
        if gate == "G1":
            ambs = extract_json_fields(raw, ("ambiguities",)).get("ambiguities") or []
            row.update(n_amb=len(ambs) if isinstance(ambs, list) else 0,
                       severities=[a.get("severity") for a in ambs if isinstance(a, dict)] if isinstance(ambs, list) else [],
                       on=bool(decisive_ambiguities(ambs)), parsed=bool(raw.strip()) and "{" in raw)
        else:
            ic, tc = _clarity_score(raw, "intent_clarity"), _clarity_score(raw, "target_certainty")
            row.update(intent=ic, target=tc, on=(ic or 0) >= 2 or (tc or 0) >= 2, parsed=ic is not None)
        row["raw"] = raw[:3000]
        rows.append(row)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

    tok_in = sum(r["usage"][0] for r in rows); tok_out = sum(r["usage"][1] for r in rows)
    print(f"calls={len(rows)} unparsed={sum(not r['parsed'] for r in rows)} tokens in/out={tok_in}/{tok_out} "
          f"≈{tok_in * 0.8e-6 + tok_out * 2.7e-6:.2f} 元")
    for gate in sorted({r["gate"] for r in rows}):
        sub = [r for r in rows if r["gate"] == gate]
        per_task = collections.defaultdict(list)
        for r in sub:
            per_task[r["task"]].append(r["on"])
        on_task = {t for t, v in per_task.items() if sum(v) * 2 > len(v)}  # 多数票
        a_on = sum(r["on"] for r in sub if r["ambiguous_14"]); a_n = sum(r["ambiguous_14"] for r in sub)
        c_on = sum(r["on"] for r in sub if not r["ambiguous_14"]); c_n = len(sub) - a_n
        overlap = len(on_task & amb) / len(amb)
        print(f"{gate}: trial 级 开启率 模糊题 {a_on}/{a_n} = {a_on / max(1, a_n):.0%}，清晰题 {c_on}/{c_n} = {c_on / max(1, c_n):.0%}；"
              f"题级（多数票）判为模糊 {len(on_task)} 道，与 14 道重合 {len(on_task & amb)}/14 = {overlap:.0%}，"
              f"误开的清晰题 {sorted(on_task - amb)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source-job", default="/root/work/jobs/e4p-contract-v1")
    p.add_argument("--k", type=int, default=3)
    p.add_argument("--concurrency", type=int, default=12)
    p.add_argument("--g2-only", action="store_true")
    p.add_argument("--no-thinking", action="store_true", help="G2 调用关掉 Seed 的思考（D-049：评分调用要快）")
    p.add_argument("--out", default="/root/work/reports/h17/gate_pilot.jsonl")
    asyncio.run(main(p.parse_args()))
