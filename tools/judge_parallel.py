"""并行版 `agenteval judge`：同一套提示与输出格式（judge.jsonl），失败 trial 用线程池并发调判官。

cmd_judge 是逐条串行调用，几十条全上下文失败要近一小时；这里按 trial 并发，结果行格式与 cmd_judge 完全一致，
`agenteval blame --judge-root` / `agenteval report --judge` 可直接读。
用法：PYTHONPATH=. .venv/bin/python tools/judge_parallel.py <job_dir> --model gpt-6-sol --out <dir> [--workers 8]
      PYTHONPATH=. .venv/bin/python tools/judge_parallel.py <job_dir> --model claude-sonnet-5 --api-key-env ANTHROPIC_API_KEY --out <dir>
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agenteval.adapters.harbor import load_job
from agenteval.adapters.tasks import full_context_for, instruction_for
from agenteval.attribute.rules import label_trial
from agenteval.judge.attribution import judge_trial
from agenteval.judge.client import JudgeClient


def main(a):
    trials = load_job(Path(a.job_dir))
    for t in trials:
        label_trial(t)
    todo = [t for t in trials if (not t.passed) and t.status in ("ok", "agent_timeout")]
    client = JudgeClient(a.model, api_key_env=a.api_key_env, reasoning_effort=a.reasoning_effort)

    def one(t):
        ins = instruction_for(t.task_name, a.tasks_root)
        full = full_context_for(t.task_name, a.tasks_root)
        vs = Path(a.job_dir) / t.trial_id / "verifier" / "test-stdout.txt"
        if vs.exists():
            txt = vs.read_text(errors="replace")
            full["verifier_stdout"] = txt if len(txt) <= 30000 else txt[:15000] + "\n[... omitted ...]\n" + txt[-15000:]
        try:
            labs = judge_trial(client, t, ins, prompt_name=a.prompt, votes=a.votes, full=full)
        except Exception as e:  # noqa: BLE001
            return {"trial_id": t.trial_id, "task": t.task_name, "attempt": t.attempt, "judge_primary": "CANNOT_JUDGE",
                    "judge_onset": None, "judge_conf": 0, "rule_labels": [l.name for l in t.labels if l.source == "RULE" and l.kind == "failure"],
                    "judge_raw": f"judge error: {e!r}"[:500]}
        prim = next((l for l in labs if l.name == "primary_failure"), None)
        return {"trial_id": t.trial_id, "task": t.task_name, "attempt": t.attempt,
                "judge_primary": prim.value if prim else "CANNOT_JUDGE", "judge_onset": prim.onset_step if prim else None,
                "judge_conf": prim.confidence if prim else 0,
                "rule_labels": [l.name for l in t.labels if l.source == "RULE" and l.kind == "failure"],
                "judge_raw": prim.comment if prim else ""}

    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(one, todo))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "judge.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    errs = sum(1 for r in rows if r["judge_raw"].startswith("judge error"))
    print(f"{len(rows)} failures judged ({errs} errors); calls={client.calls} cache_hits={client.cache_hits} usage={client.usage}; "
          f"written {out}/judge.jsonl")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="gpt-6-sol")
    ap.add_argument("--api-key-env", default="OPENAI_API_KEY")
    ap.add_argument("--reasoning-effort", default="medium")
    ap.add_argument("--prompt", default="attribution_v3.txt")
    ap.add_argument("--votes", type=int, default=1)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--tasks-root", default="/root/.cache/harbor")
    main(ap.parse_args())
