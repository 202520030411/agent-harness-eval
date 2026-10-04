import json
from pathlib import Path
from agenteval.adapters.harbor import load_job
from agenteval.adapters.tasks import instruction_for
from agenteval.attribute.rules import label_trial
g = {json.loads(l)["trial_id"]: json.loads(l) for l in open("/root/work/reports/e1-baseline-seed/judge/judge.jsonl")}
c = {json.loads(l)["trial_id"]: json.loads(l) for l in open("/root/work/reports/e1-baseline-seed/judge-claude/judge.jsonl")}
v3p = Path("/root/work/reports/e1-baseline-seed/judge-full-v3-votes3/judge.jsonl")
v3 = {json.loads(l)["trial_id"]: json.loads(l) for l in open(v3p)} if v3p.exists() else {}
def clip(s, n=5000):
    s = s or ""
    return s if len(s) <= n else s[: n // 2] + f"\n[... {len(s) - n} 字符省略 ...]\n" + s[-n // 2:]
out = []
for t in load_job(Path("/root/work/jobs/e1-baseline-seed")):
    if t.trial_id not in g: continue
    label_trial(t)
    out.append({
        "trial_id": t.trial_id, "task": t.task_name, "attempt": t.attempt, "status": t.status, "turns": t.n_episodes,
        "wall_clock_sec": t.wall_clock_sec, "instruction": instruction_for(t.task_name) or "",
        "rule_labels": [l.name for l in t.labels if l.kind == "failure"],
        "verifier_tail": (t.metadata or {}).get("verifier_stdout_tail") or "",
        "judge": {"gpt": g[t.trial_id]["judge_primary"], "gpt_onset": g[t.trial_id].get("judge_onset"), "gpt_raw": g[t.trial_id].get("judge_raw", ""),
                  "claude": c[t.trial_id]["judge_primary"], "claude_onset": c[t.trial_id].get("judge_onset"), "claude_raw": c[t.trial_id].get("judge_raw", ""),
                  "v3": v3.get(t.trial_id, {}).get("judge_primary"), "v3_onset": v3.get(t.trial_id, {}).get("judge_onset"), "v3_raw": v3.get(t.trial_id, {}).get("judge_raw", "")},
        "steps": [{"id": s.step_id, "message": s.message or "", "keystrokes": s.keystrokes, "claimed_complete": s.claimed_complete,
                   "parse_error": s.parse_error, "terminal": clip(s.observation_text), "truncated": s.truncated}
                  for s in t.agent_steps],
    })
out.sort(key=lambda r: (r["judge"]["gpt"] == r["judge"]["claude"], r["trial_id"]))
Path("/root/work/reports/e1-baseline-seed/labeling_pack/trials.json").write_text(json.dumps(out, ensure_ascii=False))
print(len(out), "trials", sum(len(r["steps"]) for r in out), "steps")
