"""agenteval analyze <harbor_job_dir> [--out DIR] [--max-turns N] [--config-id ID]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agenteval.adapters.harbor import load_job
from agenteval.attribute.rules import label_trial
from agenteval.report.metrics import render_markdown, summarize


def cmd_analyze(a):
    trials = load_job(Path(a.job_dir), config_id=a.config_id)
    max_turns = a.max_turns
    if max_turns is None:
        cfg = Path(a.job_dir) / "config.json"
        if cfg.exists():
            try:
                c = json.loads(cfg.read_text())
                max_turns = (c.get("agents") or [{}])[0].get("kwargs", {}).get("max_turns")
            except Exception:
                pass
    for t in trials:
        label_trial(t, max_turns=max_turns)
    s = summarize(trials)
    out = Path(a.out or (Path(a.job_dir).name + ".analysis"))
    out.mkdir(parents=True, exist_ok=True)
    with (out / "trials.jsonl").open("w") as f:
        for t in trials:
            f.write(json.dumps(t.to_dict(), ensure_ascii=False, default=str) + "\n")
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2, default=str))
    md = render_markdown(s, f"{Path(a.job_dir).name}")
    (out / "summary.md").write_text(md)
    print(md)
    print(f"[written] {out}/trials.jsonl, summary.json, summary.md")


def cmd_judge(a):
    import json as _json
    from agenteval.adapters.tasks import instruction_for, tests_for, full_context_for
    from agenteval.judge.attribution import judge_trial
    from agenteval.judge.client import JudgeClient
    trials = load_job(Path(a.job_dir), config_id=a.config_id)
    for t in trials:
        label_trial(t)
    todo = [t for t in trials if (not t.passed) and t.status in ("ok", "agent_timeout")]
    if a.limit: todo = todo[: a.limit]
    client = JudgeClient(a.model, api_key_env=a.api_key_env, base_url=a.base_url, reasoning_effort=a.reasoning_effort)
    out = Path(a.out or (Path(a.job_dir).name + ".judge")); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, t in enumerate(todo, 1):
        ins = instruction_for(t.task_name, a.tasks_root)
        tests = tests_for(t.task_name, a.tasks_root) if (a.with_tests and not a.blind) else None
        full = None
        if a.full_context and not a.blind:
            full = full_context_for(t.task_name, a.tasks_root)
            vs = Path(a.job_dir) / t.trial_id / "verifier" / "test-stdout.txt"
            if vs.exists():
                txt = vs.read_text(errors="replace"); full["verifier_stdout"] = txt if len(txt) <= 30000 else txt[:15000] + "\n[... omitted ...]\n" + txt[-15000:]
        labs = judge_trial(client, t, ins, prompt_name=a.prompt, blind=a.blind, tests=tests, votes=a.votes, full=full)
        t.labels += labs
        prim = next((l for l in labs if l.name == "primary_failure"), None)
        rule_names = [l.name for l in t.labels if l.source == "RULE" and l.kind == "failure"]
        rows.append({"trial_id": t.trial_id, "task": t.task_name, "attempt": t.attempt, "judge_primary": prim.value if prim else "CANNOT_JUDGE",
                     "judge_onset": prim.onset_step if prim else None, "judge_conf": prim.confidence if prim else 0, "rule_labels": rule_names,
                     "judge_raw": prim.comment if prim else ""})
        print(f"[{i}/{len(todo)}] {t.task_name}#{t.attempt}: judge={rows[-1]['judge_primary']} (onset {rows[-1]['judge_onset']}) rules={rule_names}")
    (out / "judge.jsonl").write_text("\n".join(_json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    print(f"calls={client.calls} cache_hits={client.cache_hits} usage={client.usage}; written {out}/judge.jsonl")


def cmd_report(a):
    import json as _json
    from agenteval.report.crosstab import crosstab, load_judge, render, write_labeling_sheet
    trials = load_job(Path(a.job_dir), config_id=a.config_id)
    for t in trials:
        label_trial(t)
    out = Path(a.out or (Path(a.job_dir).name + ".analysis")); out.mkdir(parents=True, exist_ok=True)
    judge = load_judge(Path(a.judge) if a.judge else out / "judge" / "judge.jsonl")
    ct = crosstab(trials, judge)
    md = render(ct); (out / "crosstab.md").write_text(md); (out / "crosstab.json").write_text(_json.dumps(ct, ensure_ascii=False, indent=2))
    n = write_labeling_sheet(trials, judge, out / "labeling_sheet.csv", a.job_dir)
    print(md); print(f"[written] {out}/crosstab.md, labeling_sheet.csv ({n} rows)")


def cmd_clarity(a):
    import json as _json
    from agenteval.adapters.tasks import instruction_for
    from agenteval.judge.aux import rate_clarity
    from agenteval.judge.client import JudgeClient
    names = [x.strip() for x in Path(a.tasks).read_text().splitlines() if x.strip() and not x.startswith("#")]
    client = JudgeClient(a.model, reasoning_effort=a.reasoning_effort)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in names:
        ins = instruction_for(n, a.tasks_root)
        if not ins: print("no instruction:", n); continue
        r = rate_clarity(client, n, ins); rows.append(r)
        print(f"{n:34} intent={r['intent_clarity']} target={r['target_certainty']} missing={str(r['missing'])[:90]}")
    out.write_text("\n".join(_json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    flagged = [r for r in rows if (r["intent_clarity"] or 0) >= 2 or (r["target_certainty"] or 0) >= 2]
    print(f"flagged (>=2 on either): {len(flagged)}/{len(rows)}; calls={client.calls} usage={client.usage}; written {out}")


def cmd_actions(a):
    import json as _json
    from agenteval.judge.aux import encode_actions, termination_stats
    from agenteval.judge.client import JudgeClient
    trials = load_job(Path(a.job_dir), config_id=a.config_id)
    client = JudgeClient(a.model, reasoning_effort=a.reasoning_effort, max_tokens=6000)
    out = Path(a.out or (Path(a.job_dir).name + ".analysis")); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, t in enumerate(trials, 1):
        r = encode_actions(client, t); rows.append(r)
        if i % 10 == 0: print(f"[{i}/{len(trials)}] calls={client.calls} cache_hits={client.cache_hits}")
    (out / "actions.jsonl").write_text("\n".join(_json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    ts = termination_stats(rows); (out / "termination.json").write_text(_json.dumps(ts, indent=2))
    from collections import Counter
    c = Counter(p for r in rows for p in r.get("phases", []))
    print("phase counts:", dict(c)); print("termination:", ts); print(f"usage={client.usage}; written {out}/actions.jsonl")


def cmd_compare(a):
    import json as _json
    from agenteval.report.compare import compare_jobs, render_compare
    ta, tb = load_job(Path(a.job_a)), load_job(Path(a.job_b))
    for t in ta + tb:
        label_trial(t)
    r = compare_jobs(ta, tb, Path(a.job_a).name, Path(a.job_b).name, n_boot=a.n_boot)
    md = render_compare(r)
    out = Path(a.out or f"{Path(a.job_b).name}_vs_{Path(a.job_a).name}.compare"); out.mkdir(parents=True, exist_ok=True)
    (out / "compare.md").write_text(md); (out / "compare.json").write_text(_json.dumps(r, ensure_ascii=False, indent=2, default=str))
    print(md); print(f"[written] {out}/compare.md")


def cmd_rubric(a):
    import json as _json
    from agenteval.adapters.tasks import instruction_for
    from agenteval.judge.client import JudgeClient
    from agenteval.rubric.pipeline import run_rubric_pipeline
    strong, weak = load_job(Path(a.strong_job)), load_job(Path(a.weak_job))
    writer = JudgeClient(a.writer_model, reasoning_effort="medium", max_tokens=3000)
    scorer = JudgeClient(a.scorer_model, reasoning_effort="low", max_tokens=1500)
    res = run_rubric_pipeline(writer, scorer, lambda n: instruction_for(n, a.tasks_root), strong, weak, max_tasks=a.max_tasks)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(res, ensure_ascii=False, indent=2))
    n_items = sum(len(r.get("items", [])) for r in res.values()); n_valid = sum(len(r.get("valid_items", [])) for r in res.values())
    for task, r in res.items():
        print(f"{task:34} items={len(r.get('items', []))} valid={r.get('valid_items')}")
    print(f"tasks={len(res)} items={n_items} valid={n_valid}; writer calls={writer.calls} scorer calls={scorer.calls}; written {out}")


def cmd_agreement(a):
    import json as _json
    from agenteval.report.agreement import agreement, load_primary, render
    x, y = load_primary(Path(a.x)), load_primary(Path(a.y))
    r = agreement(x, y, a.name_x or Path(a.x).parent.name, a.name_y or Path(a.y).parent.name)
    md = render(r); print(md)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(md)
        Path(a.out).with_suffix(".json").write_text(_json.dumps(r, ensure_ascii=False, indent=2))


def cmd_invariance(a):
    from agenteval.adapters.tasks import instruction_for
    from agenteval.judge.client import JudgeClient
    from agenteval.judge.invariance import run_invariance
    trials = load_job(Path(a.job_dir))
    for t in trials:
        label_trial(t)
    todo = [t for t in trials if (not t.passed) and t.status in ("ok", "agent_timeout")][: a.limit]
    judge = JudgeClient(a.model, reasoning_effort="medium")
    rewriter = JudgeClient(a.rewriter_model, reasoning_effort="low", max_tokens=800)
    run_invariance(judge, rewriter, todo, lambda n: instruction_for(n, a.tasks_root), Path(a.out))


def cmd_regress(a):
    import sys as _sys
    from agenteval.regression.gate import gate, render
    tasks = [x.strip() for x in Path(a.tasks).read_text().splitlines() if x.strip() and not x.startswith("#")]
    ta, tb = load_job(Path(a.baseline)), load_job(Path(a.candidate))
    r = gate(ta, tb, tasks, max_drop_pp=a.max_drop_pp)
    print(render(r))
    _sys.exit(0 if r["passed"] else 1)


def cmd_blame(a):
    from agenteval.report.blame import blame_table, render
    from agenteval.report.crosstab import load_judge
    def lj(job):
        p = Path(a.judge_root) / f"{Path(job).name}.judge.jsonl" if a.judge_root else None
        return {k: v["judge_primary"] if isinstance(v, dict) else v for k, v in load_judge(p).items()} if p and p.exists() else None
    def lt(job):
        ts = load_job(Path(job)); [label_trial(t) for t in ts]; return ts
    names = {"weak_base": Path(a.weak_base).name, "weak_mod": Path(a.weak_mod).name, "strong_base": Path(a.strong_base).name,
             "strong_mod": Path(a.strong_mod).name if a.strong_mod else None}
    judges = {k: lj(getattr(a, k)) for k in names if getattr(a, k)}
    rows = blame_table(lt(a.weak_base), lt(a.weak_mod), lt(a.strong_base), lt(a.strong_mod) if a.strong_mod else None,
                       delta=a.delta, judges=judges if a.judge_root else None)
    md = render(rows, names, a.delta); print(md)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(md)
    if a.handoff:
        from agenteval.report.handoff import render_all
        jp = Path(a.judge_root) / f"{Path(a.weak_base).name}.judge.jsonl" if a.judge_root else None
        hj = load_judge(jp) if jp and jp.exists() else {}
        Path(a.handoff).write_text(render_all(rows, lt(a.weak_base), hj)); print(f"[written] {a.handoff}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agenteval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyze", help="Harbor job 目录 → 规则标签 + 四级指标")
    p.add_argument("job_dir")
    p.add_argument("--out")
    p.add_argument("--max-turns", type=int)
    p.add_argument("--config-id")
    p.set_defaults(fn=cmd_analyze)
    j = sub.add_parser("judge", help="对失败 trial 跑盲评归因判官")
    j.add_argument("job_dir"); j.add_argument("--out"); j.add_argument("--config-id")
    j.add_argument("--model", default="gpt-6-sol"); j.add_argument("--api-key-env", default="OPENAI_API_KEY")
    j.add_argument("--base-url", default="https://api.openai.com/v1"); j.add_argument("--reasoning-effort", default="medium")
    j.add_argument("--tasks-root", default="/root/.cache/harbor"); j.add_argument("--limit", type=int)
    j.add_argument("--blind", action="store_true", help="不给判官看测试输出（判官本身的消融）")
    j.add_argument("--votes", type=int, default=1, help="majority vote over N independent samples (first uses cache)")
    j.add_argument("--with-tests", action="store_true", help="append the task's hidden test files to the judge view (post-hoc attribution only)")
    j.add_argument("--prompt", default="attribution_v2.txt", help="prompt file under agenteval/judge/prompts/ (v3 = human-arbitration decision rules)")
    j.add_argument("--full-context", action="store_true", help="D-037: all turns, relaxed clipping, full verifier output, hidden tests, environment files, reference solution")
    j.set_defaults(fn=cmd_judge)
    r = sub.add_parser("report", help="规则 × 判官交叉表 + 人工标注表")
    r.add_argument("job_dir"); r.add_argument("--out"); r.add_argument("--judge"); r.add_argument("--config-id")
    r.set_defaults(fn=cmd_report)
    c = sub.add_parser("clarity", help="指令清晰度 0–3 两维度（便宜判官）")
    c.add_argument("--tasks", required=True); c.add_argument("--out", required=True); c.add_argument("--model", default="gpt-6-luna")
    c.add_argument("--reasoning-effort", default="medium"); c.add_argument("--tasks-root", default="/root/.cache/harbor")
    c.set_defaults(fn=cmd_clarity)
    x = sub.add_parser("actions", help="TB 十类动作编码（便宜判官）")
    x.add_argument("job_dir"); x.add_argument("--out"); x.add_argument("--config-id"); x.add_argument("--model", default="gpt-6-luna")
    x.add_argument("--reasoning-effort", default="low")
    x.set_defaults(fn=cmd_actions)
    cp = sub.add_parser("compare", help="baseline A vs treatment B: paired stats + resource deltas + per-task flips")
    cp.add_argument("job_a"); cp.add_argument("job_b"); cp.add_argument("--out"); cp.add_argument("--n-boot", type=int, default=10000)
    cp.set_defaults(fn=cmd_compare)
    rb = sub.add_parser("rubric", help="strong-pass vs weak-fail pairs -> rubric items -> partial-order validation")
    rb.add_argument("strong_job"); rb.add_argument("weak_job"); rb.add_argument("--out", required=True)
    rb.add_argument("--writer-model", default="gpt-6-sol"); rb.add_argument("--scorer-model", default="gpt-6-luna")
    rb.add_argument("--tasks-root", default="/root/.cache/harbor"); rb.add_argument("--max-tasks", type=int)
    rb.set_defaults(fn=cmd_rubric)
    ag = sub.add_parser("agreement", help="two label files (judge.jsonl or human csv) -> raw agreement + Cohen's kappa")
    ag.add_argument("x"); ag.add_argument("y"); ag.add_argument("--name-x"); ag.add_argument("--name-y"); ag.add_argument("--out")
    ag.set_defaults(fn=cmd_agreement)
    iv = sub.add_parser("invariance", help="judge invariance test: paraphrase agent claims, re-judge, count flips (M3)")
    iv.add_argument("job_dir"); iv.add_argument("--out", required=True); iv.add_argument("--model", default="gpt-6-sol")
    iv.add_argument("--rewriter-model", default="gpt-6-luna"); iv.add_argument("--limit", type=int, default=30)
    iv.add_argument("--tasks-root", default="/root/.cache/harbor")
    iv.set_defaults(fn=cmd_invariance)
    rg = sub.add_parser("regress", help="regression gate: exit 1 if any listed task regressed")
    rg.add_argument("baseline"); rg.add_argument("candidate"); rg.add_argument("--tasks", required=True); rg.add_argument("--max-drop-pp", type=float, default=34.0)
    rg.set_defaults(fn=cmd_regress)
    bl = sub.add_parser("blame", help="pattern-level blame 2x2: weak/strong x baseline/modified (taxonomy.md s4)")
    bl.add_argument("--weak-base", required=True); bl.add_argument("--weak-mod", required=True); bl.add_argument("--strong-base", required=True)
    bl.add_argument("--strong-mod"); bl.add_argument("--delta", type=float, default=0.08); bl.add_argument("--judge-root", help="dir with <job>.judge.jsonl files")
    bl.add_argument("--out"); bl.add_argument("--handoff", help="also write the MODEL/MIXED handoff pack to this md path")
    bl.set_defaults(fn=cmd_blame)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
