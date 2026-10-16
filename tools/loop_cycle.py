"""自进化闭环的命令行：观察 → 反思 → 提议 → 出计划（第 1 步，不跑新实验）；评测 / 上线 / 回滚 / 回测（之后的步骤）。

  observe   读 job 目录 → 每个 trial 一行（规则标签 + 四臂实验的毛病指标）→ 失败模式表
  reflect   失败模式 → harness 队列 / 训练队列 / 人工队列（确定性，不调模型）
  propose   强模型按 harness 队列提候选；输出必须过范围检查和预注册检查才进版本记录（有硬预算）
  plan      为当前版本 + 每个候选写好 Harbor 配置和启动命令（同时跑），估算花费；**不启动任何 trial**
  evaluate  候选 job vs 基线 job → 接受门（agenteval/loop/accept.py）→ 记进版本记录
  add       人设计的候选（预注册必填）
  promote / rollback / withdraw / status
  backtest  把接受门用在历史上做过的成对实验上（含同配置的"空对照"），看它和当时的人工结论是否一致、会不会误收

本脚本没有任何启动 trial 的代码：跑实验要人按 plan 输出的命令手动启动（花钱前必须先得到批准）。
用法（服务器，仓库根目录）：PYTHONPATH=. .venv/bin/python tools/loop_cycle.py <子命令> ...
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import copy
import hashlib
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from agenteval.adapters.harbor import load_trial
from agenteval.attribute.rules import label_trial
from agenteval.loop import accept as gate
from agenteval.loop.modes import mode_table, summary
from agenteval.loop.notes import screen_note
from agenteval.loop.propose import build_prompt, candidate_texts, check_candidate, mechanism_direction, parse_response, prereg_of
from agenteval.attribute.signals import CANARY_RE
from agenteval.loop.reflect import reflect
from agenteval.loop.scope import effective_options, policy_options
from agenteval.loop.state import Registry
from terminus2_patches.helpers import appended_files, no_run_after_last_write
from tools.qarm_report import trial_row

REPO = Path(__file__).resolve().parent.parent
JOBS = Path("/root/work/jobs")
REGISTRY = REPO / "experiments/loop/registry.json"
HISTORY = REPO / "experiments/loop/history.json"
# 每百万 token 的美元价（输入, 输出）
PRICE = {"gpt-6-sol": (2.0, 10.0), "claude-sonnet-5": (3.0, 15.0)}   # claude 按偏高的价估，宁可少调
# 本地模型（"local:<served name>"）：我们自己的 vLLM，不花 API 的钱（GPU 时间另算）
LOCAL_BASE_URL = "http://127.0.0.1:8000/v1"
# 新文字要和所有题比对（D-089）：开发集、留出合成题、TB（最终报告用的题也不能被带进提醒里）
TASK_TEXT_GLOBS = ("/root/work/train/synth_split_v2/train/*/", "/root/work/train/synth_split_v2/heldout/*/",
                   "/root/.cache/harbor/tasks/packages/terminal-bench/*/*/")


def load_task_texts(globs: tuple[str, ...] = TASK_TEXT_GLOBS) -> list[str]:
    """每道题一个字符串：题面 + tests/ + solution/ 里的文本文件（每个文件最多 200 KB）。"""
    out = []
    for g in globs:
        for d in sorted(Path("/").glob(g.lstrip("/"))):
            parts = []
            for f in [d / "instruction.md", *sorted((d / "tests").rglob("*")), *sorted((d / "solution").rglob("*"))]:
                if f.is_file() and f.stat().st_size < 200_000:
                    parts.append(f.read_text(errors="ignore"))
            if parts:
                out.append("\n".join(parts))
    return out


def screen_texts(changes: dict, task_texts: list[str]) -> list[str]:
    """候选里每段会给 Qwen 看的文字都过 notes.screen_note；返回拦下的理由。"""
    probs = []
    for t in candidate_texts(changes):
        probs += [f"{t[:60]!r}: {p}" for p in screen_note(t, task_texts)]
    return probs


def code_hash(*globs: str) -> str:
    """一组源文件内容的指纹：判分代码在一轮中途被改过、两臂用的 harness 代码不一样，都能查出来。"""
    h = hashlib.sha256()
    for f in sorted({q for g in globs for q in REPO.glob(g)}):
        h.update(str(f.relative_to(REPO)).encode()); h.update(f.read_bytes())
    return h.hexdigest()[:12]


HARNESS_CODE = ("terminus2_patches/*.py",)
GATE_CODE = ("agenteval/loop/*.py", "agenteval/attribute/*.py", "tools/loop_cycle.py", "tools/qarm_report.py")


def _now() -> str:
    """美东时间的时间戳（job 名和计划文件用）。"""
    return datetime.now(ZoneInfo("America/New_York")).strftime("%m%d-%H%M")


# ---------------------------------------------------------------- observe
def _job_config(job_dir: Path) -> dict:
    for name in ("config.json", "config.yaml"):
        f = job_dir / name
        if f.exists():
            try:
                return json.loads(f.read_text()) if name.endswith(".json") else yaml.safe_load(f.read_text())
            except Exception:  # noqa: BLE001
                return {}
    return {}


def _max_turns(cfg: dict) -> int:
    for ag in cfg.get("agents") or []:
        mt = ((ag or {}).get("kwargs") or {}).get("max_turns")
        if mt:
            return int(mt)
    return 100


def _first_claim_commands(traj: dict) -> list[str] | None:
    """第一次宣布完成之前执行过的全部命令；从没宣布完成 → None。"""
    cmds: list[str] = []
    for s in traj.get("steps") or []:
        if s.get("source") != "agent":
            continue
        claimed = False
        for tc in s.get("tool_calls") or []:
            fn = tc.get("function_name")
            if fn == "bash_command":
                cmds.append(str((tc.get("arguments") or {}).get("keystrokes", "")))
            elif fn == "mark_task_complete":
                claimed = True
        if claimed:
            return cmds
    return None


def observe_trial(d: Path, arm: str, max_turns: int) -> dict | None:
    row = trial_row(arm, d)
    if row is None:
        return None
    try:
        rec = label_trial(load_trial(d), max_turns=max_turns)
        labels = sorted({l.name for l in rec.labels if l.kind == "failure"})
        counts = {l.name: l.value for l in rec.labels if l.kind == "count"}
    except Exception:  # noqa: BLE001  轨迹缺失或损坏：规则标签留空，别的字段照用
        labels, counts = [], {}
    try:
        traj = json.loads((d / "agent" / "trajectory.json").read_text())
        traj_ok = True
    except Exception:  # noqa: BLE001
        traj, traj_ok = {"steps": []}, False
    pre = _first_claim_commands(traj)
    kind = row.get("error_kind")
    if kind == "infra":
        # 报错发生在我们自己的 harness 代码里（调用栈最后一帧在 terminus2_patches）→ 候选自己崩了，算失败，不算机器故障（D-085）
        try:
            tb = ((json.loads((d / "result.json").read_text()).get("exception_info") or {}).get("exception_traceback") or "")
            frames = [l for l in tb.splitlines() if l.strip().startswith('File "')]
            if frames and "/terminus2_patches/" in frames[-1]:
                kind = "harness_error"
        except Exception:  # noqa: BLE001
            pass
    try:
        patched_meta = ((json.loads((d / "result.json").read_text()).get("agent_result") or {}).get("metadata") or {}).get("patched") or {}
    except Exception:  # noqa: BLE001
        patched_meta = {}
    if not traj_ok and kind is None:
        kind = "infra"                                     # 没有轨迹：轮数等字段都不可信，按数据缺失处理
    steps = [s for s in traj.get("steps") or [] if s.get("source") == "agent"]
    keys = [[str((tc.get("arguments") or {}).get("keystrokes", "")) for tc in (s.get("tool_calls") or [])
             if tc.get("function_name") == "bash_command"] for s in steps]
    toks = [int(((s.get("metrics") or {}).get("prompt_tokens")) or 0) for s in steps]
    try:
        patched = ((json.loads((d / "result.json").read_text()).get("agent_result") or {}).get("metadata") or {}).get("patched") or {}
        bounce = int(patched["completion_gate"][0]["turn"]) if patched.get("completion_gate") else None
    except Exception:  # noqa: BLE001
        bounce = None
    return {
        "trial": row["trial"], "task": row["task"], "passed": row["passed"], "error": row.get("error"), "error_kind": kind,
        "infra": kind == "infra", "timeout": kind == "timeout", "turns": row.get("turns") if traj_ok else None, "max_turns": max_turns,
        "turn_cap": (row.get("turns") or 0) >= max_turns, "minutes": row.get("minutes"),
        "tokens_in": row.get("tokens_in"), "tokens_out": row.get("tokens_out"),
        "n_parse_err": row.get("n_parse_err"), "json_loop_end": row.get("json_loop_end"), "cnf": row.get("cnf"),
        "echo_theater": row.get("echo_theater"), "false_success": row.get("false_success"), "declared": row.get("declared"),
        "no_run_before_claim": bool(pre is not None and no_run_after_last_write(pre)),
        "polling_turns": counts.get("polling_turns"), "rule_labels": labels,
        "append_turns": sum(1 for ks in keys if any(appended_files(k) for k in ks)),
        "turns_after_gate": max(0, len(steps) - bounce) if bounce is not None else 0,
        "tokens_in_after_gate": sum(toks[bounce:]) if bounce is not None else 0,
        "gate_fired": row.get("gate_fired"), "gate_reasons": row.get("gate_reasons"),
        "integrity_flag": "INTEGRITY_SUSPECT" in labels or bool(CANARY_RE.search(json.dumps(traj))),
        "cheat_confirmed": bool(CANARY_RE.search(json.dumps(traj))) or any("/opt/grader" in k for ks in keys for k in ks),
        "harness_code": patched_meta.get("code_hash"),
        "declared_fail": bool(row.get("declared")) and not row["passed"],
    }


def observe_jobs(jobs: list[str], arm: str = "H0", jobs_root: Path = JOBS) -> list[dict]:
    rows = []
    for job in jobs:
        jd = jobs_root / job
        mt = _max_turns(_job_config(jd))
        for d in sorted(jd.glob("*__*/")):
            r = observe_trial(d, arm, mt)
            if r is None:                                  # result.json 读不出来：记成故障，计入故障率，不能悄悄消失
                r = {"trial": d.name, "task": d.name.split("__")[0], "passed": False, "infra": True, "error_kind": "missing_result",
                     "timeout": False, "turns": None}
            r["job"] = job
            rows.append(r)
    return rows


def cmd_observe(a) -> None:
    rows = observe_jobs(a.jobs.split(","), a.arm)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with open(out / "rows.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    table = mode_table(rows)
    (out / "observe.json").write_text(json.dumps({"jobs": a.jobs.split(","), "summary": summary(rows), "modes": table},
                                                 ensure_ascii=False, indent=1))
    print(_render_modes(summary(rows), table, a.jobs))


def _render_modes(s: dict, table: list[dict], jobs: str) -> str:
    L = [f"# 观察：{jobs}", "",
         f"- trial {s['n_trials']}（基础设施故障 {s['n_infra']}），{s['n_tasks']} 题；通过率 {100*(s['pass_rate'] or 0):.1f}%；"
         f"超时 {s['timeouts']}；平均轮数 {s['mean_turns'] and round(s['mean_turns'], 1)}；平均分钟 {s['mean_minutes'] and round(s['mean_minutes'], 1)}", "",
         "| 模式 | 分母 | 次数 | 比例 | 占失败 | 涉及题数 | 先验归责 |", "|---|---|---|---|---|---|---|"]
    for m in sorted(table, key=lambda m: -m["share_of_failures"]):
        L.append(f"| {m['label']} | {'全部' if m['among'] == 'all' else '失败'} {m['denominator']} | {m['n']} | {100*m['rate']:.0f}% | "
                 f"{100*m['share_of_failures']:.0f}% | {m['n_tasks']} | {m['prior']} |")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- reflect
def cmd_reflect(a) -> None:
    obs_dir = Path(a.observe)
    obs = json.loads((obs_dir / "observe.json").read_text())
    rows = [json.loads(l) for l in open(obs_dir / "rows.jsonl")]
    history = json.loads(Path(a.history).read_text()) if Path(a.history).exists() else []
    r = reflect(obs["modes"], rows, history, min_rate=a.min_rate, min_n=a.min_n)
    (obs_dir / "reflect.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    L = ["# 反思", "", f"题目难度（每题 {a.attempts_hint} 次左右）：{r['task_difficulty']}", "", "## harness 队列"]
    for t in r["harness_targets"]:
        L.append(f"- **{t['label']}**（{t['mode']}）：{t['n']}/{t['denominator']}，占失败 {100*t['share_of_failures']:.0f}%；"
                 f"先验 {t['prior']}；试过：{[x['id'] for x in t['tried']] or '无'}")
    L += ["", "## 训练队列（模型侧）"] + [f"- {t['label']}：占失败 {100*t['share_of_failures']:.0f}%" for t in r["model_targets"]]
    L += ["", "## 人工队列"] + [f"- {t['label']}：{t.get('why')}" for t in r["human_review"]]
    (obs_dir / "reflect.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


# ---------------------------------------------------------------- propose
class Budget:
    def __init__(self, usd: float):
        self.cap, self.spent = usd, 0.0

    def charge(self, model: str, usage: dict) -> float:
        pin, pout = PRICE.get(model, (5.0, 25.0))
        c = usage.get("prompt_tokens", 0) / 1e6 * pin + usage.get("completion_tokens", 0) / 1e6 * pout
        self.spent += c
        return c

    def allow(self, model: str, prompt_chars: int, max_out: int) -> bool:
        pin, pout = PRICE.get(model, (5.0, 25.0))
        est = prompt_chars / 3.0 / 1e6 * pin + max_out / 1e6 * pout     # 保守：3 字符 / token，输出按上限算
        return self.spent + est <= self.cap


def cmd_propose(a) -> None:
    from agenteval.judge.client import JudgeClient
    obs_dir = Path(a.observe)
    rf = json.loads((obs_dir / "reflect.json").read_text())
    targets = rf["harness_targets"]
    if not targets:
        print("harness 队列为空：这一轮没有可提议的目标"); return
    history = json.loads(Path(a.history).read_text()) if Path(a.history).exists() else []
    context = json.loads(Path(a.context).read_text()) if a.context else {}
    context["development_set_summary"] = json.loads((obs_dir / "observe.json").read_text())["summary"]
    budget = Budget(a.budget_usd)
    target_ids = {t["mode"] for t in targets}
    added, rejected, reviews, notes = [], [], [], []
    playbook = Path(a.playbook).read_text() if getattr(a, "playbook", None) else None
    pb_name = Path(a.playbook).stem if playbook else "legacy"
    task_texts: list[str] | None = None
    with Registry.edit(a.registry) as reg:
        if not reg.current:
            sys.exit("registry not initialised: run `init` first")
        previous = [{"version": v.version, "status": v.status, "change": v.change, "notes": v.notes}
                    for v in reg.versions.values() if v.parent is not None]
        system, user = build_prompt(reg.current_options(), targets, history, context, k_auto=a.k_auto, k_review=a.k_review,
                                    previous=previous, playbook=playbook)
        (obs_dir / f"propose_prompt_{pb_name}.txt").write_text(system + "\n\n" + user)
        for spec in a.models.split(","):
            local = spec.startswith("local:")             # "local:coder30b:1" = 我们自己 vLLM 上的模型（Qwen 当提议者）
            model, _, n = (spec[len("local:"):] if local else spec).partition(":")   # "gpt-6-sol:2" = 独立问 2 次
            for sample in range(int(n) if n else a.samples):
                max_out = max(a.max_tokens, 4000) + 24000 if model.startswith("claude") else a.max_tokens   # judge/client.py 给 claude 加了思考余量
                if not local and not budget.allow(model, len(system) + len(user), max_out):
                    notes.append(f"budget: skipped {model} sample {sample} (spent ${budget.spent:.2f} of ${budget.cap:.2f})"); continue
                u = user if sample == 0 else user + f"\n\n(independent attempt #{sample + 1}: think from a different angle)"
                client = None
                try:
                    if local:
                        import os
                        os.environ.setdefault("LOCAL_LLM_KEY", "EMPTY")
                        client = JudgeClient(model, api_key_env="LOCAL_LLM_KEY", base_url=LOCAL_BASE_URL, reasoning_effort=None,
                                             max_tokens=a.max_tokens, provider="openai")
                    else:
                        client = JudgeClient(model, reasoning_effort=a.effort, max_tokens=a.max_tokens)
                    text = client.complete(system, u)
                except Exception as e:  # noqa: BLE001
                    if client is not None and not local:   # 调用失败但已经计费（比如只返回了思考）也要记账
                        budget.charge(model, client.usage)
                    notes.append(f"{model} sample {sample}: call failed: {e}"); continue
                cost = 0.0 if local else budget.charge(model, client.usage)
                (obs_dir / f"propose_raw_{pb_name}_{model}_{sample}.txt").write_text(text)
                try:
                    obj = parse_response(text)
                except ValueError as e:
                    notes.append(f"{model} sample {sample}: {e}"); continue
                cands = obj.get("auto_candidates") or []
                if not isinstance(cands, list):
                    cands = []
                if len(cands) > a.k_auto:                   # 候选数上限由代码卡死，不只写在提示里
                    notes.append(f"{model} sample {sample}: returned {len(cands)} auto candidates; kept the first {a.k_auto}")
                    cands = cands[:a.k_auto]
                for c in cands:
                    errs = check_candidate(c, target_ids)
                    if not errs and candidate_texts(c.get("changes")):
                        if task_texts is None:
                            task_texts = load_task_texts()
                        errs = screen_texts(c["changes"], task_texts)
                    if not errs:
                        v, errs = reg.propose(reg.current, c["changes"], rationale=str(c.get("mechanism", "")), prereg=prereg_of(c),
                                              source=f"proposer:{'local:' if local else ''}{model}#{sample}@{pb_name}")
                        if v is not None:
                            v.prereg["mechanism_direction"] = mechanism_direction(c)
                            added.append(v.version)
                            reg.save(a.registry)            # 每进一个候选就存盘：后面出错也不会丢掉已经花钱拿到的结果
                            continue
                    rejected.append({"from": f"{model}#{sample}", "changes": c.get("changes") if isinstance(c, dict) else c, "errors": errs})
                for r in obj.get("review_proposals") or []:
                    if isinstance(r, dict):
                        reviews.append({"from": f"{model}#{sample}", **r})
                notes.append(f"{model} sample {sample}: ${cost:.3f}; {len(cands)} auto, "
                             f"{len(obj.get('review_proposals') or [])} review, {len(obj.get('rejected_ideas') or [])} rejected-by-model")
        lines = []
        for vid in added:
            v = reg.versions[vid]
            lines.append(f"- **{vid}**：{v.change}；目标 {v.prereg.get('target_mode')}；机制指标 {v.prereg.get('mechanism_metric')}"
                         f"（{v.prereg.get('predicted_mechanism_change')}）；通过率预测 {v.prereg.get('predicted_pass_change')}；"
                         f"证伪：{v.prereg.get('falsified_if')}（{v.source}）")
    report = {"added": added, "rejected": rejected, "review_proposals": reviews, "notes": notes, "spent_usd": round(budget.spent, 4)}
    (obs_dir / f"propose_{pb_name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    L = [f"# 提议（花费 ${budget.spent:.3f}，上限 ${budget.cap:.2f}）", "", "## 进入版本记录的候选"] + lines
    L += ["", "## 被拒的候选（范围 / 预注册 / 重复）"] + [f"- {r['from']} {r['changes']}：{r['errors']}" for r in rejected]
    L += ["", "## 需要人审的提案（不会自动生效）"] + [f"- [{r['from']}] **{r.get('title')}**（{r.get('target_mode')}）：{r.get('what_to_build')}" for r in reviews]
    L += ["", "## 记录"] + [f"- {n}" for n in notes]
    (obs_dir / f"propose_{pb_name}.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


# ---------------------------------------------------------------- init / plan / evaluate / promote / rollback / status
def cmd_init(a) -> None:
    cfg = yaml.safe_load(open(a.from_config))
    ag = cfg["agents"][0]
    with Registry.edit(a.registry) as reg:
        reg.init_root(a.version, ag["name"], ag.get("kwargs") or {}, rationale=a.rationale, model=ag.get("model_name") or "")
        print(f"initialised {a.version} ({ag.get('model_name')}): {reg.current_options()}")


PROTOCOL_KEYS = ("api_base", "parser_name", "max_turns", "enable_summarize", "proactive_summarization_threshold", "model_info")
CONFIG_DIR = REPO / "experiments/configs"


def _sidecar_path(job: str, config_dir: Path = CONFIG_DIR) -> Path:
    return Path(config_dir) / f"{job}.loop.json"


def cmd_plan(a) -> None:
    """写一轮的 Harbor 配置：当前版本 + 候选，全部同时启动、平分并发。只写文件，不启动。
    默认 = 父版本是当前版本、状态 proposed 的候选的主评测；--replicate V = V 的复现批次（两臂都新跑）；
    --rerun V = V 上一次评测是 INVALID，换新 job 重跑；--retest V --reason D-xxx = 判分规则改过之后重测一次主评测是
    INCONCLUSIVE 的 V（D-088），可以和新候选放在同一批、共用基线。每个 job 旁边写一个 .loop.json 记下这一轮的信息
    （判分代码和 harness 代码的指纹、候选数、用途），evaluate 用它核对。"""
    reg = Registry.load(a.registry)
    tpl = yaml.safe_load(open(a.template))
    refs: dict[str, str] = {}
    a.retest, a.reason = getattr(a, "retest", None), getattr(a, "reason", None)
    if (a.replicate or a.rerun) and a.retest:
        sys.exit("--retest cannot be combined with --replicate / --rerun")
    if a.replicate or a.rerun:
        vid = a.replicate or a.rerun
        v = reg.versions[vid]
        counted = lambda purpose: [e for e in v.evaluations if e["purpose"] == purpose and e["decision"] != "INVALID"]
        if a.replicate:
            prim = counted("retest") or counted("primary")          # 有重测（D-088）就看重测
            if v.status != "evaluated" or not prim or prim[0]["decision"] not in ("ACCEPT_QUALITY", "ACCEPT_EFFICIENCY", "PROVISIONAL") \
                    or counted("replication"):
                sys.exit(f"{vid} cannot be replicated (status {v.status}, evaluations {[e['decision'] for e in v.evaluations]})")
            purpose = "replication"
        else:
            if not v.evaluations or v.evaluations[-1]["decision"] != "INVALID":
                sys.exit(f"{vid}: only an INVALID evaluation can be re-run")
            purpose = v.evaluations[-1]["purpose"]
            if purpose == "retest":
                refs[vid] = v.evaluations[-1].get("decision_ref", "")
        if v.parent != reg.current:
            sys.exit(f"{vid}'s parent {v.parent} is no longer the current version {reg.current}")
        cands = [v]
    else:
        cands = [v for v in reg.versions.values() if v.status == "proposed" and v.parent == reg.current]
        if a.only:
            keep = set(a.only.split(","))
            cands = [v for v in cands if v.version in keep]
        purpose = "primary"
        if a.retest:
            if not a.reason:
                sys.exit("--retest needs --reason (the decision record that changed the gate, e.g. D-088)")
            v = reg.versions[a.retest]
            prim = [e for e in v.evaluations if e["purpose"] == "primary" and e["decision"] != "INVALID"]
            if v.status != "evaluated" or not prim or prim[0]["decision"] != "INCONCLUSIVE" or \
                    any(e["purpose"] == "retest" and e["decision"] != "INVALID" for e in v.evaluations):
                sys.exit(f"{a.retest} cannot be retested (status {v.status}, evaluations {[e['decision'] for e in v.evaluations]})")
            if prim[0].get("gate_code") == code_hash(*GATE_CODE):
                sys.exit(f"{a.retest}: the gate code has not changed since its primary evaluation; a retest would judge the same way")
            if v.parent != reg.current:
                sys.exit(f"{a.retest}'s parent {v.parent} is no longer the current version {reg.current}")
            cands.append(v)
            refs[v.version] = a.reason
    if not cands:
        sys.exit("no candidates to plan")
    unapproved = [v.version for v in cands if reg.needs_text_approval(v.version)]
    if unapproved:
        sys.exit(f"text not yet approved by a human for {unapproved}: run `approve-text` after the text has been reviewed (D-089)")
    arms = [("base", reg.versions[reg.current])] + [(v.version, v) for v in cands]
    tag = a.tag or _now()
    per_arm = max(1, a.concurrency // len(arms))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cfg_dir = Path(a.config_dir); cfg_dir.mkdir(parents=True, exist_ok=True)   # tools/launch_job.sh 只认这个目录
    jobs = {name: f"loop-{tag}-{name.replace('+', '-')}" for name, _ in arms}
    info = {"tag": tag, "purpose": purpose, "base_version": reg.current, "baseline_job": jobs["base"],
            "candidate_jobs": {n: j for n, j in jobs.items() if n != "base"}, "n_comparisons": len(cands),
            "gate_code": code_hash(*GATE_CODE), "harness_code": code_hash(*HARNESS_CODE), "anchor_rows": a.anchor_rows}
    for name, v in arms:
        job = jobs[name]
        f = cfg_dir / f"{job}.resolved.yaml"
        if f.exists() or _sidecar_path(job, cfg_dir).exists():
            sys.exit(f"{f} already exists; pick another --tag")
        cfg = copy.deepcopy(tpl)
        cfg["job_name"] = job
        cfg["n_attempts"] = a.k
        cfg.setdefault("orchestrator", {})["n_concurrent_trials"] = per_arm
        ag = cfg["agents"][0]
        kw = {k: v2 for k, v2 in (ag.get("kwargs") or {}).items() if k in PROTOCOL_KEYS}
        kw.update(policy_options(v.options))
        kw["raw_log"] = True
        ag["name"], ag["kwargs"] = v.agent, kw
        f.write_text(f"# 自进化闭环 {tag}（{purpose}）：{name}；有效配置 {json.dumps(effective_options(v.options), ensure_ascii=False)}\n"
                     + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
        side = {**info, "arm": name, "version": v.version, "model": ag.get("model_name")}
        if v.version in refs:
            side["purpose"], side["decision_ref"] = "retest", refs[v.version]
        _sidecar_path(job, cfg_dir).write_text(json.dumps(side, ensure_ascii=False, indent=1))
    trials = len(arms) * a.n_tasks * a.k
    hours = trials * a.minutes_per_trial / max(1, per_arm * len(arms)) / 60
    gpu_usd = (hours + a.setup_hours) * a.gpu_usd_per_hour
    L = [f"# 计划 {tag}（{purpose}；只写配置，不启动）", "",
         f"- 臂：{', '.join(n for n, _ in arms)}；每臂 {a.n_tasks} 题 × {a.k} 次，总并发 {per_arm * len(arms)}（每臂 {per_arm}），全部同时启动（D-040）",
         f"- trial 总数 {trials}；按每次 {a.minutes_per_trial} 分钟估计约 {hours:.1f} 小时；GPU 约 ${gpu_usd:.0f}（含 {a.setup_hours} 小时起服务）",
         f"- 判分代码指纹 {info['gate_code']}、harness 代码指纹 {info['harness_code']}：评测时任何一个变了都会拒绝评测",
         "", "## 启动命令（花钱前必须先得到批准）：所有臂放在同一条命令里，launch_job.sh 先全部检查、再同时启动（D-040）",
         f"    bash tools/launch_job.sh {' '.join(jobs.values())}",
         "", "## 评测命令（跑完后）"] + [f"    PYTHONPATH=. .venv/bin/python tools/loop_cycle.py evaluate --version {n} "
                                       f"--baseline-job {jobs['base']} --candidate-job {jobs[n]} --anchor-rows {a.anchor_rows}"
                                       for n, _ in arms[1:]]
    (out / f"plan-{tag}.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


def _job_window(jobs: list[str]) -> tuple | None:
    starts, ends = [], []
    for job in jobs:
        for f in (JOBS / job).glob("*__*/result.json"):
            try:
                ae = json.loads(f.read_text()).get("agent_execution") or {}
                if ae.get("started_at") and ae.get("finished_at"):
                    starts.append(datetime.fromisoformat(ae["started_at"].replace("Z", "+00:00")))
                    ends.append(datetime.fromisoformat(ae["finished_at"].replace("Z", "+00:00")))
            except Exception:  # noqa: BLE001
                continue
    return (min(starts), max(ends)) if starts else None


def concurrency(base_jobs: list[str], cand_jobs: list[str], max_start_gap_min: float = 15.0, min_overlap: float = 0.8) -> tuple[bool, dict]:
    """两臂算"同时跑"：开跑时间相差不超过 15 分钟，而且运行时段重合至少占较短那一臂的 80%。从 result.json 里的时间读，不靠人声明。"""
    wa, wb = _job_window(base_jobs), _job_window(cand_jobs)
    if wa is None or wb is None:
        return False, {"error": "no timing data"}
    gap = abs((wa[0] - wb[0]).total_seconds()) / 60
    overlap = max(0.0, (min(wa[1], wb[1]) - max(wa[0], wb[0])).total_seconds())
    shorter = max(1.0, min((wa[1] - wa[0]).total_seconds(), (wb[1] - wb[0]).total_seconds()))
    info = {"start_gap_min": round(gap, 1), "overlap_frac": round(overlap / shorter, 3)}
    return gap <= max_start_gap_min and overlap / shorter >= min_overlap, info


def cmd_evaluate(a) -> None:
    base_jobs, cand_jobs = a.baseline_job.split(","), a.candidate_job.split(",")
    sc = json.loads(_sidecar_path(cand_jobs[0]).read_text()) if _sidecar_path(cand_jobs[0]).exists() else None
    if sc is None or sc.get("version") != a.version or sc.get("baseline_job") != base_jobs[0]:
        sys.exit("evaluate only accepts runs written by `plan` (no matching .loop.json for this version and baseline job)")
    gate_now = code_hash(*GATE_CODE)
    if sc["gate_code"] != gate_now:
        sys.exit(f"the evaluation code changed after this round was planned ({sc['gate_code']} -> {gate_now}); refusing to evaluate")
    base, cand = observe_jobs(base_jobs), observe_jobs(cand_jobs)
    codes = {r.get("harness_code") for r in base + cand if not r.get("infra")} - {None}
    if len(codes) > 1:
        sys.exit(f"the two arms ran different harness code {sorted(codes)}; refusing to evaluate")
    conc, cinfo = concurrency(base_jobs, cand_jobs)
    anchor_rows = [json.loads(l) for l in open(a.anchor_rows)]
    with Registry.edit(a.registry) as reg:
        v = reg.versions[a.version]
        mech = (v.prereg.get("mechanism_metric"), v.prereg.get("mechanism_direction", "decrease")) if v.prereg.get("mechanism_metric") else None
        d = gate.evaluate(base, cand, concurrent=conc, cfg=gate.GateConfig(n_comparisons=sc.get("n_comparisons", 1)),
                          mechanism=mech, anchor_rows=anchor_rows)
        reg.record_evaluation(a.version, d, baseline_job=a.baseline_job, candidate_job=a.candidate_job, purpose=sc["purpose"],
                              extra={"concurrency": cinfo, "gate_code": gate_now, "harness_code": sorted(codes),
                                     "n_comparisons": sc.get("n_comparisons", 1), "margin_pp": d.get("margin_pp"),
                                     **({"decision_ref": sc["decision_ref"]} if sc.get("decision_ref") else {})})
    print(json.dumps(d, ensure_ascii=False, indent=1))


def cmd_add(a) -> None:
    """人设计的候选（比如 review 档批准后的新机制）：和提议模型的候选一样，必须预注册、过范围检查和查重。"""
    prereg = json.loads(Path(a.prereg).read_text())
    changes = json.loads(a.changes)
    if candidate_texts(changes):                       # 人写的文字也要过同一道过滤（D-089）
        probs = screen_texts(changes, load_task_texts())
        if probs:
            sys.exit(f"refused by the text screen: {probs}")
    with Registry.edit(a.registry) as reg:
        v, errs = reg.propose(a.parent or reg.current, changes, rationale=a.rationale, prereg=prereg,
                              source=f"human:{a.by}")
        if v is None:
            sys.exit(f"refused: {errs}")
        v.prereg["mechanism_direction"] = mechanism_direction(prereg)
        print(f"added {v.version}: {v.change}")


def cmd_discover(a) -> None:
    """自动找毛病（D-089）：两家模型各读一遍失败轨迹，一致才采信；都说是新毛病的再归一次类；做找回测试；归类结果过泄题检查。
    花的是 API 的钱：每次调用前按上限检查，超了就停（已经拿到的结果照样写出来）。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from agenteval.judge.client import JudgeClient
    from agenteval.loop import discover as dc

    rows = [json.loads(l) for l in open(a.rows)]
    by_trial = {r["trial"]: r for r in rows}
    picks = dc.pick_trials(rows, n=a.n, seed=a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    budget, lock = Budget(a.budget_usd), threading.Lock()
    models = a.models.split(",")
    notes: list[str] = []

    def trial_dir(name: str) -> Path:
        return JOBS / by_trial[name]["job"] / name

    def view(name: str, contrast: bool = False) -> str:
        traj = json.loads((trial_dir(name) / "agent" / "trajectory.json").read_text())
        return dc.condense(traj, head=3, tail=8, max_chars=12000) if contrast else dc.condense(traj)

    def prompt_for(p: dict) -> tuple[str, str]:
        d = trial_dir(p["trial"])
        task_dir = Path(a.tasks) / p["task"]
        instr = (task_dir / "instruction.md").read_text() if (task_dir / "instruction.md").exists() else "(instruction not found)"
        so = (d / "verifier" / "test-stdout.txt").read_text(errors="ignore") if (d / "verifier" / "test-stdout.txt").exists() else ""
        return dc.judge_prompt(instr, dc.failure_summary(so), view(p["trial"]), view(p["contrast"], True) if p["contrast"] else None)

    def call(model: str, system: str, user: str, max_tokens: int) -> tuple[str | None, str]:
        with lock:
            if not budget.allow(model, len(system) + len(user), max_tokens + (24000 if model.startswith("claude") else 0)):
                return None, f"budget: skipped {model} (spent ${budget.spent:.2f} of ${budget.cap:.2f})"
        client = JudgeClient(model, reasoning_effort=a.effort, max_tokens=max_tokens)
        try:
            text = client.complete(system, user)
            err = ""
        except Exception as e:  # noqa: BLE001
            text, err = None, f"{model}: call failed: {e}"
        with lock:
            budget.charge(model, client.usage)
        return text, err

    def judge(p: dict) -> dict:
        system, user = prompt_for(p)
        res = {"trial": p["trial"], "task": p["task"], "contrast": p["contrast"], "judges": {}}
        for m in models:
            text, err = call(m, system, user, 1500)
            if text is None:
                res["judges"][m] = {"error": err}
                continue
            try:
                res["judges"][m] = dc.parse_judgement(text)
            except Exception as e:  # noqa: BLE001
                res["judges"][m] = {"error": f"unparseable: {e}", "raw": text[:500]}
        return res

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        judged = list(ex.map(judge, picks))
    with open(out / "judgements.jsonl", "w") as f:
        for j in judged:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    ok = lambda j, m: j["judges"].get(m) if "category" in (j["judges"].get(m) or {}) else None
    for j in judged:
        j["agreement"] = dc.agree(ok(j, models[0]), ok(j, models[1])) if len(models) == 2 else {"status": "single_judge"}
    known = Counter(j["agreement"]["category"] for j in judged if j["agreement"]["status"] == "known")
    new_items = [dict(j["agreement"], trial=j["trial"]) for j in judged if j["agreement"]["status"] == "new"]
    disputed = [dict(j["agreement"], trial=j["trial"]) for j in judged if j["agreement"]["status"] == "disputed"]
    failed = [j["trial"] for j in judged if j["agreement"]["status"] == "judge_failed"]
    clusters: list[dict] = []
    if new_items:
        system, user = dc.cluster_prompt(new_items, k=a.k_clusters)
        text, err = call(models[0], system, user, 4000)
        if text is None:
            notes.append(err)
        else:
            try:
                clusters = dc.parse_clusters(text, len(new_items))
            except Exception as e:  # noqa: BLE001
                notes.append(f"clustering unparseable: {e}")
    # 归类结果交给提议模型之前过泄题检查：只看"带进了某道题的内容"那两条（描述里出现 tests 之类的词在这里是正常的）
    task_texts = load_task_texts()
    for c in clusters:
        c["n"] = len(c["items"])
        c["share_of_sample"] = round(c["n"] / max(1, len(judged)), 3)
        c["trials"] = [new_items[i - 1]["trial"] for i in c["items"]]
        probs = screen_note(" ".join([c["name"], c["definition"], c["detection_rule"]]), task_texts)
        c["leak_flags"] = [x for x in probs if x.startswith(("shares a 6-word", "uses an identifier"))]
    every = [{"behaviors": [((j["judges"].get(m) or {}).get("behavior") or "") for m in models],
              "truth": (by_trial[j["trial"]].get("append_turns") or 0) >= 10} for j in judged]
    redisc = dc.rediscovered_append(clusters, every)
    rec = "-" if redisc["recall"] is None else f"{100 * redisc['recall']:.0f}%"
    report = {"rows": a.rows, "n_judged": len(judged), "models": models, "spent_usd": round(budget.spent, 3),
              "agreement": {"known": sum(known.values()), "new": len(new_items), "disputed": len(disputed), "judge_failed": len(failed)},
              "known_counts": dict(known.most_common()), "clusters": clusters, "disputed": disputed, "judge_failed": failed,
              "rediscovery_line_by_line_write": redisc, "notes": notes}
    (out / "discover.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    L = [f"# 自动找毛病：{a.rows}", "", f"- 判了 {len(judged)} 条失败轨迹（{' + '.join(models)}），花费 ${budget.spent:.2f}（上限 ${budget.cap:.2f}）",
         f"- 两家一致归到已知毛病 {sum(known.values())}、都说是新毛病 {len(new_items)}、有分歧 {len(disputed)}、判官失败 {len(failed)}",
         f"- 找回测试（逐行追加，判官清单里没有这个名字）：真有逐行追加的 {redisc['n_truth']} 条里召回 {rec}；"
         f"命中的新类别 {redisc['clusters'] or '无'} → {'找回来了' if redisc['found'] else '没找回来'}", "",
         "## 已知毛病（两家一致）"] + [f"- {k}: {n}" for k, n in known.most_common()]
    L += ["", "## 新毛病（归类后；≥5% 的才写固定规则、人工核对后进模式表）"]
    for c in sorted(clusters, key=lambda c: -c["n"]):
        L.append(f"- **{c['name']}**（{c['n']} 条，占样本 {100*c['share_of_sample']:.0f}%；harness 能修：{c['harness_fixable']}）"
                 f"{'；⚠ 泄题标记 ' + str(c['leak_flags']) if c['leak_flags'] else ''}：{c['definition']}")
        L.append(f"  - 怎么认：{c['detection_rule']}")
    L += ["", "## 有分歧（交给人看）"] + [f"- {d['trial']}: {d['categories']} — {d['behaviors']}" for d in disputed]
    L += ["", "## 记录"] + [f"- {n}" for n in notes]
    (out / "discover.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


def cmd_rewrite_playbook(a) -> None:
    """提议模型改写自己的 playbook（D-089）：证据只来自版本记录里的预测和结果。写出候选文件和 diff，不直接启用：
    第一次改写要人看过 diff、同意后把 <name>.candidate.md 改名为 <name>.md 才能用于 propose --playbook。"""
    from agenteval.judge.client import JudgeClient
    from agenteval.loop import playbook as pb

    old = Path(a.playbook).read_text()
    reg = Registry.load(a.registry)
    ev = pb.evidence({k: asdict(v) for k, v in reg.versions.items()})
    system, user = pb.build_prompt(old, ev)
    budget = Budget(a.budget_usd)
    if not budget.allow(a.model, len(system) + len(user), a.max_tokens):
        sys.exit("over budget")
    client = JudgeClient(a.model, reasoning_effort=a.effort, max_tokens=a.max_tokens)
    text = client.complete(system, user)
    cost = budget.charge(a.model, client.usage)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / f"{out.stem}.raw.txt").write_text(text)
    obj = pb.parse(text)
    task_texts = load_task_texts()
    probs = pb.check(obj["playbook"], ev, obj["changes"], lambda t: screen_note(t, task_texts))
    out.write_text(obj["playbook"].strip() + "\n")
    name_old, name_new = Path(a.playbook).stem, out.stem.replace(".candidate", "")
    diff = pb.unified_diff(old, obj["playbook"].strip() + "\n", name_old, name_new)
    (out.parent / f"{out.stem}.diff").write_text(diff)
    (out.parent / f"{out.stem}.changes.json").write_text(json.dumps({"changes": obj["changes"], "problems": probs, "cost_usd": round(cost, 4),
                                                                     "evidence": ev}, ensure_ascii=False, indent=1))
    print(diff)
    print(json.dumps(obj["changes"], ensure_ascii=False, indent=1))
    print(f"cost ${cost:.3f}; problems: {probs or 'none'}")
    if probs:
        sys.exit("the new playbook failed the checks above; it must not be used")


VETO_SYSTEM = ("You check text that will be shown to a terminal coding agent while it is being evaluated. You can only flag problems; "
               "you cannot approve anything.")
VETO_TEMPLATE = """The text below would be inserted into the agent's context (as a short note attached to terminal output, or as a how-to
document it may open). Flag it if ANY of these is true:
(a) it would mainly help on tasks made by one particular task generator or one task family, for example rules about exact output
    formatting (trailing newlines, JSON spacing, CSV line endings, column order) or about specific file names, ports or tools;
(b) it hints at expected outputs, hidden tests, grading, reference solutions or answers;
(c) it pushes the agent to stop, submit, or do less work.
General advice about how to work in a terminal (writing files, checking one's own results, getting unstuck) is fine.

TEXT:
{text}

Return ONLY a JSON object: {{"veto": true or false, "reasons": ["<short reason>", ...]}}"""


def cmd_veto_text(a) -> None:
    """另一家模型（默认 claude-sonnet-5）对候选的文字做一次只能否决的审查（D-089）；否决就撤下这个候选。花 API 的钱，有上限。"""
    from agenteval.judge.client import JudgeClient
    with Registry.edit(a.registry) as reg:
        v = reg.versions[a.version]
        texts = candidate_texts(v.change)
        if not texts:
            sys.exit(f"{a.version} has no text")
        user = VETO_TEMPLATE.format(text="\n---\n".join(texts))
        budget = Budget(a.budget_usd)
        if not budget.allow(a.model, len(VETO_SYSTEM) + len(user), a.max_tokens + 24000):
            sys.exit("over budget")
        client = JudgeClient(a.model, reasoning_effort="low", max_tokens=a.max_tokens)
        text = client.complete(VETO_SYSTEM, user)
        cost = budget.charge(a.model, client.usage)
        m = re.search(r"\{.*\}", re.sub(r"```(?:json)?", "", text or ""), re.S)
        try:
            obj = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            obj = {}
        if "veto" not in obj:                         # 审查结果读不出来：按否决处理，宁可少测一个候选
            obj = {"veto": True, "reasons": [f"unreadable review: {(text or '')[:200]}"]}
        verdict = f"text review by {a.model}: {'VETO' if obj['veto'] else 'no objection'} {obj.get('reasons')} (${cost:.3f})"
        v.notes.append(verdict)
        if obj["veto"]:
            reg.withdraw(a.version, verdict)
        print(verdict)


def cmd_approve_text(a) -> None:
    """人读过候选的全部文字（提醒、skill）之后才运行；先把文字打印出来，确认的就是这一份（D-089）。"""
    with Registry.edit(a.registry) as reg:
        v = reg.versions[a.version]
        print(json.dumps({k: v.change[k] for k in v.change if k in ("custom_notes", "skills")}, ensure_ascii=False, indent=1))
        reg.approve_text(a.version, by=a.by, note=a.note)
        print(f"approved text of {a.version} (by {a.by})")


def cmd_promote(a) -> None:
    with Registry.edit(a.registry) as reg:
        reg.promote(a.version)
        print(f"current = {reg.current}; lineage {reg.lineage()}")


def cmd_rollback(a) -> None:
    with Registry.edit(a.registry) as reg:
        print(f"rolled back; current = {reg.rollback(a.reason)}")


def cmd_withdraw(a) -> None:
    with Registry.edit(a.registry) as reg:
        reg.withdraw(a.version, a.reason)
        print(f"withdrew {a.version}: {a.reason}")


def cmd_status(a) -> None:
    reg = Registry.load(a.registry)
    print(f"current: {reg.current}  lineage: {reg.lineage() if reg.current else []}")
    for v in reg.versions.values():
        last = v.evaluations[-1]["decision"] if v.evaluations else "-"
        print(f"  {v.version:16s} {v.status:12s} model={v.model or '-':16s} last={last:18s} change={v.change}")


# ---------------------------------------------------------------- backtest
def cmd_backtest(a) -> None:
    """pairs 文件：[{"id", "baseline": [job...], "candidate": [job...], "concurrent": bool, "expected": "人工结论", "null": bool}]"""
    pairs = json.loads(Path(a.pairs).read_text())
    cache: dict[str, list[dict]] = {}

    def rows(jobs):
        key = ",".join(jobs)
        if key not in cache:
            cache[key] = observe_jobs(jobs)
        return cache[key]
    results = []
    for p in pairs:
        b, c = rows(p["baseline"]), rows(p["candidate"])
        if not b or not c:
            results.append({**p, "decision": "MISSING", "reasons": ["job not found"]}); continue
        common = {r["task"] for r in b} & {r["task"] for r in c}
        b2, c2 = [r for r in b if r["task"] in common], [r for r in c if r["task"] in common]
        hist_cfg = gate.GateConfig(allow_nonconcurrent=True)          # 历史回测：允许不同时跑（ACCEPT 降为 PROVISIONAL）
        d = gate.evaluate(b2, c2, concurrent=p.get("concurrent", False), cfg=hist_cfg)
        relaxed = None
        if d["decision"] == gate.INVALID and all("usable attempts" in x for x in d["reasons"]):
            # 只因每题次数不够而无效：再按每题 1 次放宽看一眼门会怎么说（仅供参考，不是门的决定）
            relaxed = gate.evaluate(b2, c2, concurrent=p.get("concurrent", False),
                                    cfg=gate.GateConfig(min_attempts_per_task=1, allow_nonconcurrent=True))
            d = {**relaxed, "decision": gate.INVALID, "reasons": d["reasons"]}
        results.append({**p, "decision": d["decision"], "reasons": d["reasons"], "pass": d.get("pass"),
                        "efficiency": d.get("efficiency"), "timeout": d.get("timeout"), "anchors": d.get("anchors"),
                        "relaxed_decision": relaxed and relaxed["decision"], "relaxed_reasons": relaxed and relaxed["reasons"],
                        "n_tasks": len(common), "attempts": [len(b2), len(c2)]})
    null = _null_splits(a.null_jobs.split(",") if a.null_jobs else [], rows, a.null_draws)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "backtest.json").write_text(json.dumps({"pairs": results, "null_splits": null}, ensure_ascii=False, indent=1))
    L = ["# 接受门回测：历史上做过的成对实验"]
    for title, rs in (("## 改动 vs 基线", [r for r in results if not r.get("null")]),
                      ("## 同配置空对照（两边配置相同：任何 ACCEPT 都是误收）", [r for r in results if r.get("null")])):
        L += ["", title, "", "| 对比 | 题数 | trial（基线/候选） | 同时跑 | 通过率 Δ（pp）[95% 区间] | 超时 Δ（pp） | 效率变化 | 门的决定 | 当时的人工结论 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in rs:
            ps, to = r.get("pass") or {}, r.get("timeout") or {}
            eff = ", ".join(f"{m} {100*(e.get('rel') or 0):+.0f}%" for m, e in (r.get("efficiency") or {}).items())
            dec = f"**{r['decision']}**" + (f"（放宽次数要求后：{r['relaxed_decision']}）" if r.get("relaxed_decision") else "")
            L.append(f"| {r['id']} | {r.get('n_tasks', '—')} | {'/'.join(map(str, r.get('attempts', [])))} | {'是' if r.get('concurrent') else '否'} | "
                     f"{ps.get('delta', '—')} {ps.get('ci', '')} | {to.get('delta', '—')} | {eff or '—'} | {dec} | {r.get('expected', '')} |")
    L += ["", "## 门给出的理由"] + [f"- {r['id']}：{'；'.join(r['reasons'])}" + (f"（放宽后：{'；'.join(r['relaxed_reasons'])}）" if r.get('relaxed_reasons') else "")
                                  for r in results]
    if null:
        L += ["", f"## 空对照：同一配置的 trial 随机分成两半当成两个臂（每个 job 抽 {a.null_draws} 次）", "",
              "| job（@ 后是锚题用的更早批次） | 抽样次数 | 决定分布 | 误收率（ACCEPT_*） | 误拒率（REJECT） |", "|---|---|---|---|---|"]
        for job, s in null.items():
            L.append(f"| {job} | {s['draws']} | {s['decisions']} | {100*s['false_accept_rate']:.1f}% | {100*s['false_reject_rate']:.1f}% |")
    (out / "backtest.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


def _null_splits(jobs: list[str], rows_fn, draws: int) -> dict:
    """同一配置（同一 job、或几个同配置 job 合起来）的 trial，按题随机分成两半，当作"基线 vs 候选"喂给门。
    门在这里的任何 ACCEPT 都是误收：用来估计门的假阳性率。"""
    out = {}
    for spec in jobs:
        spec, _, hist = spec.partition("@")          # "a+b@c+d"：a、b 合起来随机对半分；c、d 当作更早的观察批次（锚题用）
        rs = rows_fn(spec.split("+"))
        anchor_rows = rows_fn(hist.split("+")) if hist else None
        by_task: dict[str, list[dict]] = {}
        for r in rs:
            by_task.setdefault(r["task"], []).append(r)
        if not by_task:                                   # job 名写错之类：跳过，不让整个回测白跑
            out[spec] = {"draws": 0, "decisions": {}, "false_accept_rate": 0.0, "false_reject_rate": 0.0, "error": "no trials"}
            continue
        dec = Counter()
        rng = random.Random(0)
        for _ in range(draws):
            A, B = [], []
            for t, lst in by_task.items():
                lst = lst[:]
                rng.shuffle(lst)
                h = len(lst) // 2
                A += lst[:h]; B += lst[h:2 * h]
            cfg = gate.GateConfig(min_attempts_per_task=max(1, min(len(v) for v in by_task.values()) // 2), n_boot=2000)
            dec[gate.evaluate(A, B, concurrent=True, cfg=cfg, anchor_rows=anchor_rows)["decision"]] += 1
        acc = sum(v for k, v in dec.items() if k.startswith("ACCEPT"))
        out[spec + (f" @ {hist}" if hist else "")] = {"draws": draws, "decisions": dict(dec), "false_accept_rate": acc / max(1, draws),
                                                     "false_reject_rate": dec.get(gate.REJECT, 0) / max(1, draws)}
    return out


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("observe"); s.add_argument("--jobs", required=True); s.add_argument("--arm", default="H0"); s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_observe)
    s = sub.add_parser("reflect"); s.add_argument("--observe", required=True); s.add_argument("--history", default=str(HISTORY))
    s.add_argument("--min-rate", type=float, default=0.05); s.add_argument("--min-n", type=int, default=5); s.add_argument("--attempts-hint", default="3")
    s.set_defaults(fn=cmd_reflect)
    s = sub.add_parser("propose"); s.add_argument("--observe", required=True); s.add_argument("--registry", default=str(REGISTRY))
    s.add_argument("--history", default=str(HISTORY)); s.add_argument("--context")
    s.add_argument("--models", default="gpt-6-sol:2,claude-sonnet-5:1"); s.add_argument("--samples", type=int, default=1)
    s.add_argument("--effort", default="high"); s.add_argument("--max-tokens", type=int, default=12000)
    s.add_argument("--k-auto", type=int, default=4); s.add_argument("--k-review", type=int, default=3)
    s.add_argument("--budget-usd", type=float, default=1.5)
    s.add_argument("--playbook", help="规则那一块用哪个 playbook 文件（experiments/loop/playbooks/P0.md …）；不给用第 1 轮的写法")
    s.set_defaults(fn=cmd_propose)
    s = sub.add_parser("discover"); s.add_argument("--rows", required=True, help="observe 输出的 rows.jsonl（当前版本那一臂）")
    s.add_argument("--tasks", default="/root/work/train/synth_split_v2/train"); s.add_argument("--n", type=int, default=80)
    s.add_argument("--seed", type=int, default=0); s.add_argument("--models", default="gpt-6-sol,claude-sonnet-5")
    s.add_argument("--effort", default="low"); s.add_argument("--workers", type=int, default=8); s.add_argument("--k-clusters", type=int, default=6)
    s.add_argument("--budget-usd", type=float, default=8.0); s.add_argument("--out", required=True); s.set_defaults(fn=cmd_discover)
    s = sub.add_parser("rewrite-playbook"); s.add_argument("--registry", default=str(REGISTRY))
    s.add_argument("--playbook", required=True); s.add_argument("--out", required=True, help="例如 experiments/loop/playbooks/P1.candidate.md")
    s.add_argument("--model", default="gpt-6-sol"); s.add_argument("--effort", default="high"); s.add_argument("--max-tokens", type=int, default=8000)
    s.add_argument("--budget-usd", type=float, default=1.0); s.set_defaults(fn=cmd_rewrite_playbook)
    s = sub.add_parser("veto-text"); s.add_argument("--registry", default=str(REGISTRY)); s.add_argument("--version", required=True)
    s.add_argument("--model", default="claude-sonnet-5"); s.add_argument("--max-tokens", type=int, default=1500)
    s.add_argument("--budget-usd", type=float, default=0.3); s.set_defaults(fn=cmd_veto_text)
    s = sub.add_parser("approve-text"); s.add_argument("--registry", default=str(REGISTRY)); s.add_argument("--version", required=True)
    s.add_argument("--by", required=True, help="批准的人"); s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_approve_text)
    s = sub.add_parser("init"); s.add_argument("--version", required=True); s.add_argument("--from-config", required=True)
    s.add_argument("--rationale", required=True); s.add_argument("--registry", default=str(REGISTRY)); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("plan"); s.add_argument("--registry", default=str(REGISTRY)); s.add_argument("--template", required=True)
    s.add_argument("--replicate", help="为这个版本写复现批次（两臂都新跑）"); s.add_argument("--rerun", help="这个版本上次 INVALID，换新 job 重跑")
    s.add_argument("--retest", help="判分规则改过之后重测这个版本（主评测是 INCONCLUSIVE，D-088）"); s.add_argument("--reason")
    s.add_argument("--n-tasks", type=int, required=True); s.add_argument("--k", type=int, default=4); s.add_argument("--concurrency", type=int, default=16)
    s.add_argument("--minutes-per-trial", type=float, default=4.8); s.add_argument("--gpu-usd-per-hour", type=float, default=4.6)
    s.add_argument("--setup-hours", type=float, default=0.3); s.add_argument("--only"); s.add_argument("--tag")
    s.add_argument("--anchor-rows", default="/root/work/reports/loop/c1/rows.jsonl")
    s.add_argument("--out", default=str(REPO / "experiments/loop/plans"))
    s.add_argument("--config-dir", default=str(REPO / "experiments/configs")); s.set_defaults(fn=cmd_plan)
    s = sub.add_parser("evaluate"); s.add_argument("--registry", default=str(REGISTRY)); s.add_argument("--version", required=True)
    s.add_argument("--baseline-job", required=True); s.add_argument("--candidate-job", required=True)
    s.add_argument("--anchor-rows", required=True, help="当前版本更早的观察批次（observe 输出的 rows.jsonl）：锚题要求两批都全过")
    s.set_defaults(fn=cmd_evaluate)
    s = sub.add_parser("add"); s.add_argument("--registry", default=str(REGISTRY)); s.add_argument("--parent")
    s.add_argument("--changes", required=True, help='JSON，例如 \'{"append_nudge": true}\''); s.add_argument("--prereg", required=True)
    s.add_argument("--rationale", required=True); s.add_argument("--by", required=True); s.set_defaults(fn=cmd_add)
    s = sub.add_parser("promote"); s.add_argument("--registry", default=str(REGISTRY)); s.add_argument("--version", required=True)
    s.set_defaults(fn=cmd_promote)
    s = sub.add_parser("rollback"); s.add_argument("--registry", default=str(REGISTRY)); s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_rollback)
    s = sub.add_parser("status"); s.add_argument("--registry", default=str(REGISTRY)); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("withdraw"); s.add_argument("--registry", default=str(REGISTRY)); s.add_argument("--version", required=True)
    s.add_argument("--reason", required=True); s.set_defaults(fn=cmd_withdraw)
    s = sub.add_parser("backtest"); s.add_argument("--pairs", required=True); s.add_argument("--null-jobs", default="")
    s.add_argument("--null-draws", type=int, default=200); s.add_argument("--out", required=True); s.set_defaults(fn=cmd_backtest)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
