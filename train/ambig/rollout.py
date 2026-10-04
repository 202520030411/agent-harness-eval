"""在进程内环境里跑任意 OpenAI 兼容模型：老师（Seed，火山）采轨迹，或学生（vLLM 上的 Qwen）做评测。

用法（服务器）：
  source ~/.secrets.env
  python rollout.py --model openai/doubao-seed-2-1-lite-260915 --api-base https://ark.cn-beijing.volces.com/api/v3 \
      --api-key-env ARK_API_KEY --split train --n 20 --out /root/work/train/seed_smoke.jsonl
  python rollout.py --model openai/qwen3-8b --api-base http://127.0.0.1:8000/v1 --api-key-env NONE --split heldout ...
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import litellm  # noqa: E402

from env import Episode  # noqa: E402
from generator import make_split  # noqa: E402

SPLITS = {"train": 100_000, "heldout": 900_000}   # seed 起点，保证不重叠


async def run_episode(task, a, sem):
    ep = Episode(task)
    usage = [0, 0]
    async with sem:
        while not ep.done:
            try:
                r = await litellm.acompletion(model=a.model, api_base=a.api_base, messages=ep.messages,
                                              api_key=(os.environ.get(a.api_key_env) if a.api_key_env != "NONE" else "EMPTY"),
                                              max_tokens=a.max_tokens, **({"temperature": a.temperature} if a.temperature is not None else {}),
                                              **({"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}} if a.no_think else {}))
                text = r.choices[0].message.content or ""
                if getattr(r, "usage", None):
                    usage[0] += r.usage.prompt_tokens or 0; usage[1] += r.usage.completion_tokens or 0
            except Exception as e:  # noqa: BLE001
                ep.messages.append({"role": "assistant", "content": f"<<api error {e!r}>>"[:300]})
                break
            ep.step(text)
    rec = ep.record()
    rec["model"] = a.model
    rec["usage"] = usage
    return rec


async def main(a):
    tasks = make_split(a.n, SPLITS[a.split] + a.offset, needs_evidence=None if a.mix else True, difficulty=a.difficulty)
    tasks = [t for t in tasks for _ in range(a.k)]
    sem = asyncio.Semaphore(a.concurrency)
    recs = await asyncio.gather(*(run_episode(t, a, sem) for t in tasks))
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n")
    by = collections.defaultdict(list)
    for r in recs:
        by["ALL"].append(r); by["evidence" if r["needs_evidence"] else "clear"].append(r); by[r["family"]].append(r)
    print(f"{'group':16s} {'n':>4s} {'pass':>6s} {'read_ev':>8s} {'pass|read':>10s} {'pass|noread':>12s} {'turns':>6s} {'invalid':>8s}")
    for g, rs in sorted(by.items(), key=lambda kv: (kv[0] != "ALL", kv[0])):
        rd = [r for r in rs if r["read_evidence"]]; nr = [r for r in rs if not r["read_evidence"]]
        f = lambda xs: f"{sum(x['reward'] for x in xs)}/{len(xs)}" if xs else "-"
        print(f"{g:16s} {len(rs):4d} {sum(r['reward'] for r in rs) / len(rs):6.0%} {len(rd) / len(rs):8.0%} {f(rd):>10s} {f(nr):>12s} "
              f"{sum(r['turns'] for r in rs) / len(rs):6.1f} {sum(r['invalid'] for r in rs):8d}")
    ev = [r for r in recs if r["needs_evidence"]]
    if ev:
        fe = sorted(r["first_evidence_turn"] for r in ev if r.get("first_evidence_turn"))
        med = fe[len(fe) // 2] if fe else None
        print(f"evidence tasks: saw-evidence {sum(r['read_evidence'] for r in ev)}/{len(ev)}, median turn of first evidence {med}, "
              f"turn-cap {sum(r['turn_cap'] for r in ev)}/{len(ev)}, searches/episode {sum(r['n_search'] for r in ev) / len(ev):.1f}")
    tin = sum(r["usage"][0] for r in recs); tout = sum(r["usage"][1] for r in recs)
    print(f"tokens in/out {tin}/{tout}; Seed lite price ≈ {tin * 0.8e-6 + tout * 2.7e-6:.2f} yuan ({(tin * 0.8e-6 + tout * 2.7e-6) / len(recs):.4f}/episode)")
    print(f"[written] {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--api-base", required=True)
    p.add_argument("--api-key-env", default="ARK_API_KEY")
    p.add_argument("--split", choices=sorted(SPLITS), default="train")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--k", type=int, default=1, help="每题采样次数")
    p.add_argument("--mix", action="store_true", help="混入约 25% 清晰版对照题（默认全是缺约定题）")
    p.add_argument("--difficulty", choices=["easy", "hard"], default="easy", help="hard：证据放中性路径、无关文件更多")
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--no-think", action="store_true", help="vLLM 上的 Qwen3：关闭思考（与 SFT 的 --thinking off 一致）")
    p.add_argument("--out", required=True)
    asyncio.run(main(p.parse_args()))
