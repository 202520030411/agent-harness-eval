"""用 gpt-6-sol 出合成题（QWEN_PLAN §4.1）：每个 (技能族, 场景, 变体号) 一道，输出题目描述 JSON（题面、工作区文件、隐藏测试、参考解）。
出题模型只拿到 families.py 里的抽象描述（防污染）；调用走 agenteval 的 JudgeClient（重试、磁盘缓存、token 计数），重跑不重复花钱。
用法（服务器，需 OPENAI_API_KEY）：
  python train/synth/generate.py --out /root/work/train/synth_specs --per-family 1 --families log-regex,sqlite-query,local-service   # 试点
  python train/synth/generate.py --out /root/work/train/synth_specs --per-family 25                                                 # 正式
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agenteval.judge.client import JudgeClient  # noqa: E402
from train.synth.families import DOMAINS, FAMILIES  # noqa: E402

HERE = Path(__file__).parent
PRICE_IN, PRICE_OUT = 2.0e-6, 1.0e-5          # gpt-6-sol，美元 / token（思考过程按输出计）
REQUIRED = ("task_id", "title", "instruction", "apt_packages", "pip_packages", "workspace_files", "setup_script", "tests", "solution",
            "self_check")


def parse_spec(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    spec = json.loads(t[start:end + 1])
    missing = [k for k in REQUIRED if k not in spec]
    if missing:
        raise ValueError(f"missing fields {missing}")
    if not isinstance(spec["workspace_files"], dict):
        raise ValueError("workspace_files must be an object")
    spec["task_id"] = re.sub(r"[^a-z0-9-]+", "-", str(spec["task_id"]).lower()).strip("-")[:48] or "task"
    return spec


def jobs(families: list[str], per_family: int) -> list[tuple[str, str, int]]:
    out = []
    for fi, fam in enumerate(families):
        for k in range(per_family):
            dom = DOMAINS[(k + 7 * fi) % len(DOMAINS)]   # 各族错开场景，避免同一场景扎堆
            out.append((fam, dom, k))
    return out


def main(a) -> None:
    system = (HERE / "prompts" / "generator.txt").read_text()
    fams = [f for f in (a.families.split(",") if a.families else FAMILIES) if f]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "ok": 0, "bad": 0}

    def one(fam: str, dom: str, k: int):
        f = out / f"{fam}__{k:02d}.json"
        if f.exists():
            return f"skip {f.name}"
        user = f"SKILL: {FAMILIES[fam]}\nDOMAIN: {dom}\nVARIATION: {k}\nReturn only the JSON object."
        cli = JudgeClient(a.model, reasoning_effort=a.effort, max_tokens=a.max_tokens)
        try:
            text = cli.complete(system, user)
            spec = parse_spec(text)
        except Exception as e:  # noqa: BLE001
            with lock:
                usage["bad"] += 1
                usage["prompt_tokens"] += cli.usage["prompt_tokens"]; usage["completion_tokens"] += cli.usage["completion_tokens"]
            return f"FAIL {fam} {k}: {e!r}"[:200]
        spec["_meta"] = {"family": fam, "domain": dom, "variation": k, "model": a.model, "effort": a.effort, "usage": dict(cli.usage)}
        f.write_text(json.dumps(spec, ensure_ascii=False, indent=1))
        with lock:
            usage["ok"] += 1
            usage["prompt_tokens"] += cli.usage["prompt_tokens"]; usage["completion_tokens"] += cli.usage["completion_tokens"]
        return f"ok {f.name} ({spec['task_id']}, {cli.usage['completion_tokens']} out tokens)"

    todo = jobs(fams, a.per_family)
    with ThreadPoolExecutor(a.concurrency) as ex:
        for fut in as_completed([ex.submit(one, *j) for j in todo]):
            print(fut.result(), flush=True)
    cost = usage["prompt_tokens"] * PRICE_IN + usage["completion_tokens"] * PRICE_OUT
    n = max(1, usage["ok"] + usage["bad"])
    print(f"done: ok {usage['ok']} bad {usage['bad']} | tokens in {usage['prompt_tokens']} out {usage['completion_tokens']} "
          f"| new spend ${cost:.2f} (${cost / n:.3f} per call; cached calls cost 0)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--families", default="")
    ap.add_argument("--per-family", type=int, default=1)
    ap.add_argument("--model", default="gpt-6-sol")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--max-tokens", type=int, default=32000)
    ap.add_argument("--concurrency", type=int, default=8)
    main(ap.parse_args())
