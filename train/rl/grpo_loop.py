"""PSP 式 GRPO 主循环（D-072；在 Hetzner 上跑，Pod 负责 vLLM 与每步的一次参数更新）。

  选 16 道训练题（固定打乱顺序循环）──▶ 该带提示的题：rules 模式把规则放题面最前（gpt-6-sol 读该题最近一组失败写的）；
                                          teacher 模式单独一个 job 开 D-069 实时 Teacher
  ──▶ Harbor：当前策略每题 8 次（H2，采样设置同评测）──▶ 判分 0/1 → 组内 advantage（grpo.py）
  ──▶ Pod：停 vLLM → grpo_step.py 一次 LoRA 更新 → serve_policy.sh 挂新策略 ──▶ 日志 / 止损 / 存状态

不蒸馏：训练 token 全是 Qwen 自己采样的；提示在 user 消息里，不算 loss（PSP：特权信息留在上下文里、不进 loss）。
可以随时重跑：状态存 <rl-dir>/state.json（每步结束才写），每一步的各阶段按产物是否已存在跳过（D-066：长任务靠完成标记）。
止损：第 1 步有信号的组 < --min-signal-groups；最近 3 步平均通过率比最初 3 步低 10 pp 以上；平均输出 token 超过第 1 步的 2 倍；
      从 RL 开始算的 GPU 小时 × 单价 + API 花费 > --budget-usd。
key：本进程不加载任何 key。写规则时起子进程临时读 ~/.secrets.env；Harbor 由 tools/launch_job.sh / launch_teacher_job.sh 启动。
用法（Hetzner，tmux 里；评测和试点都结束、没有别的 job 在用 vLLM 之后）：
  PYTHONPATH=. .venv/bin/python train/rl/grpo_loop.py --hint-mode rules --rl-dir /root/work/rl_smoke --prefix smoke --steps 2 \
      --tasks-per-step 4 --attempts 4 --concurrency 16 --min-signal-groups 1 --only-tasks a,b,c,d        # 冒烟
  PYTHONPATH=. .venv/bin/python train/rl/grpo_loop.py --hint-mode rules --rl-dir /root/work/rl --prefix rl --steps 20 --budget-usd 120  # 正式
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from train.rl.grpo import HINTED, PLAIN, group_advantages, next_mode, pick_tasks, trial_example, trial_reward  # noqa: E402
from train.synth.psp_rules import PRICE_IN, PRICE_OUT, knowledge_text, render_block  # noqa: E402

REPO = Path("/root/work/agent_harness")
JOBS = Path("/root/work/jobs")
TRAIN = Path("/root/work/train/synth_split/train")
HARD = Path("/root/work/train/teacher_knowledge.json")          # 前两轮 0/6 的 51 道（D-069）
PILOT_RULES = Path("/root/work/train/psp_rules.json")            # D-072 试点：这 51 道的规则，读的是原版在第一、二轮的失败
TEMPLATE = REPO / "experiments" / "configs" / "qroll-h2-synth-train.resolved.yaml"
POD = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15",
       "-p", os.environ.get("POD_PORT", "22"), "root@" + os.environ.get("POD_HOST", "gpu-pod")]   # GPU 机器地址从环境变量读


def say(msg: str) -> None:
    print(f"{dt.datetime.now(ZoneInfo('America/New_York')):%H:%M} {msg}", flush=True)


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------- 纯函数（有单测）
def write_config(template: str, job: str, dataset: Path, model: str, attempts: int, conc: int, teacher_knowledge: str | None) -> str:
    """由采样配置（H2、存完整对话）改出本步的 Harbor 配置。"""
    y = re.sub(r"\A# .*", f"# RL（D-072）{job}：由 train/rl/grpo_loop.py 生成", template, count=1)
    for pat, rep in ((r"^job_name: .*$", f"job_name: {job}"), (r"^n_attempts: .*$", f"n_attempts: {attempts}"),
                     (r"n_concurrent_trials: \d+", f"n_concurrent_trials: {conc}"), (r"model_name: openai/\S+", f"model_name: openai/{model}"),
                     (r"- path: \S+", f"- path: {dataset}")):
        y, n = re.subn(pat, rep, y, count=1, flags=re.M)
        assert n == 1, f"template field not found: {pat}"
    if teacher_knowledge:
        y = y.replace("    store_all_messages: true\n", f"    store_all_messages: true\n    teacher_hint: true\n    teacher_knowledge: {teacher_knowledge}\n")
    return y


def share_concurrency(trials: dict[str, int], total: int) -> dict[str, int]:
    """一步里几个 job（主 job、Teacher job、不带提示的试做 job）同时跑：按各自的 trial 数分摊总并发，合计不超过 total
    （负载太高每轮变慢、超时变多，D-074）。每个 job 至少 1。"""
    n = sum(trials.values())
    out = {j: max(1, int(total * t / n)) for j, t in trials.items()}
    while sum(out.values()) > total and max(out.values()) > 1:
        j = max(out, key=out.get)
        out[j] -= 1
    return out


def build_batch(groups: dict[str, list[tuple[dict, float]]], rules_blocks: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    """组内 advantage → 训练样本；全对 / 全错的组没有信号。rules_blocks：带规则的题 → 放在题面前的规则原文（算提示依赖度用）。"""
    rules_blocks = rules_blocks or {}
    rows, why, signal = [], collections.Counter(), 0
    for task in sorted(groups):
        g = groups[task]
        adv = group_advantages([rew for _, rew in g])
        if adv is None:
            why["group_without_signal"] += 1
            continue
        signal += 1
        for (r, _), a in zip(g, adv):
            ex, reason = trial_example(r, a, rules_blocks.get(task))
            why[reason] += 1
            if ex:
                rows.append(ex)
    return rows, {"signal_groups": signal, **why}


def step_stats(groups: dict[str, list[tuple[dict, float]]], mode: dict[str, str]) -> dict:
    rew = lambda m: [x for t, g in groups.items() if m is None or mode[t] == m for _, x in g]   # noqa: E731
    return {"trials": len(rew(None)), "pass_rate": mean(rew(None)), "pass_rate_plain": mean(rew(PLAIN)), "pass_rate_hinted": mean(rew(HINTED)),
            "passes_by_task": {t: [int(sum(x for _, x in g)), len(g)] for t, g in sorted(groups.items())},
            "mean_out_tokens": mean(((r.get("agent_result") or {}).get("n_output_tokens")) for g in groups.values() for r, _ in g)}


def teacher_usd(groups: dict[str, list[tuple[dict, float]]]) -> float:
    """teacher 模式：Harbor 里 Teacher 调用的实际 token（metadata.patched.teacher.calls[].usage）折成美元。"""
    usd = 0.0
    for g in groups.values():
        for r, _ in g:
            patched = (((r.get("agent_result") or {}).get("metadata") or {}).get("patched") or {})
            for c in (patched.get("teacher") or {}).get("calls", []):
                u = c.get("usage") or {}
                usd += u.get("prompt_tokens", 0) * PRICE_IN + u.get("completion_tokens", 0) * PRICE_OUT
    return usd


def teacher_health(groups: dict[str, list[tuple[dict, float]]]) -> tuple[int, int]:
    """(Teacher 调用次数, 其中出错的次数)。出错多半是 API 额度用完或 key 失效：Teacher 连错 3 次会自己熔断、学生照常做完，
    训练不会报错，只是悄悄变成“不带提示”——所以要单独数出来，交给 stop_reason。"""
    calls = errs = 0
    for g in groups.values():
        for r, _ in g:
            patched = (((r.get("agent_result") or {}).get("metadata") or {}).get("patched") or {})
            for c in (patched.get("teacher") or {}).get("calls", []):
                calls += 1
                errs += str(c.get("drop_reason") or "").startswith("teacher_error")
    return calls, errs


def stop_reason(history: list[dict], min_signal: int, spent: float, budget: float) -> str | None:
    if spent > budget:
        return f"BUDGET (${spent:.0f} > ${budget:.0f})"
    tc, te = history[-1].get("teacher_calls", 0), history[-1].get("teacher_errors", 0)
    if tc >= 10 and te * 2 > tc:
        return f"TEACHER_FAILING ({te}/{tc} teacher calls errored — API credits or key?)"
    if len(history) == 1 and history[0]["batch"]["signal_groups"] < min_signal:
        return f"NO_SIGNAL ({history[0]['batch']['signal_groups']} groups with signal < {min_signal})"
    if len(history) >= 6:
        # 只比“同一道题、同一种模式（带不带提示）”：整步平均通过率每步换一批题，而且 next_mode 会把带提示做对的题改成不带提示，
        # 策略不变时整步平均也会系统性往下掉（固定策略的模拟：teacher 模式下旧规则误停约 85%，中位第 7–8 步）
        first, d = {}, []
        for h in history[:-3]:
            for t, (p, n) in (h.get("passes_by_task") or {}).items():
                if n:
                    first.setdefault((t, t in h.get("hinted", [])), p / n)
        for h in history[-3:]:
            for t, (p, n) in (h.get("passes_by_task") or {}).items():
                key = (t, t in h.get("hinted", []))
                if n and key in first:
                    d.append(p / n - first[key])
        if len(d) >= 8 and mean(d) < -0.10:
            return f"PASS_RATE_DROP (same task, same mode: {mean(d):+.2f} over {len(d)} pairs)"
    t0 = history[0].get("mean_out_tokens")
    if t0 and (history[-1].get("mean_out_tokens") or 0) > 2 * t0:
        return f"LENGTH_BLOWUP ({t0:.0f} → {history[-1]['mean_out_tokens']:.0f} output tokens / trial)"
    return None


# ---------------------------------------------------------------- 与 Pod / Harbor 打交道
def bg(cmd: str, log: str, marker: str) -> str:
    """Pod 上后台跑 cmd（在 /workspace/code 下），结束时把退出码写进 marker。
    只能让这一条命令进后台：写成 "cd … && setsid … &" 时，& 会把整个 "cd && …" 放进一个没重定向输出的子 shell，
    它占着 ssh 连接直到任务结束，ssh 就一直不返回（2026-09-27 23:54 冒烟因此超时退出，D-078）。"""
    return (f"cd /workspace/code; setsid nohup bash -c '{cmd} > {log} 2>&1; echo rc=$? > {marker}' "
            f"< /dev/null > /dev/null 2>&1 &")


def pod(cmd: str, timeout: int = 120) -> str:
    r = subprocess.run(POD + [cmd], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"pod command failed ({r.returncode}): {cmd[:100]} :: {r.stderr[-300:]}")
    return r.stdout


def pod_poll(cmd: str, done, limit_sec: int, every: int = 30) -> str:
    """反复在 Pod 上跑 cmd，直到 done(输出) 为真；连接偶尔断就下一轮再查。"""
    t0 = time.time()
    while time.time() - t0 < limit_sec:
        try:
            out = pod(cmd, timeout=60)
            if done(out):
                return out
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        time.sleep(every)
    raise RuntimeError(f"timeout after {limit_sec}s: {cmd[:100]}")


def served_models() -> str:
    return subprocess.run(["curl", "-sf", "-m", "10", "http://127.0.0.1:8000/v1/models"], capture_output=True, text=True).stdout


def serve(pod_dir: str, name: str) -> None:
    if f'"{name}"' in served_models():
        return
    out = f"{pod_dir}/serve_{name}.txt"
    pod(f"rm -f {out}; setsid nohup bash /workspace/code/serve_policy.sh {name} {pod_dir}/{name} > {out} 2>&1 < /dev/null &", timeout=60)
    txt = pod_poll(f"cat {out} 2>/dev/null || true", lambda s: "SERVE_POLICY_" in s, 1800, 20)
    if "SERVE_POLICY_OK" not in txt:
        raise RuntimeError(f"serve failed: {txt[-400:]}")
    for _ in range(30):                      # 隧道那头也要看得到
        if f'"{name}"' in served_models():
            return
        time.sleep(10)
    raise RuntimeError(f"{name} served on the pod but not visible through the tunnel")


def train_on_pod(pod_dir: str, step: int, prev: str, new: str, batch: Path, lr: float) -> dict:
    sd = f"{pod_dir}/step{step:02d}"
    marker = f"{sd}/train_done.txt"
    if pod(f"cat {marker} 2>/dev/null || true").strip() != "rc=0":
        pod(f"mkdir -p {sd}")
        with open(batch) as f:
            subprocess.run(POD + [f"cat > {sd}/batch.jsonl"], stdin=f, check=True, timeout=900)
        pod(f"rm -f {marker}; pkill -f '[v]llm serve'; sleep 20; " + bg(
            f"/workspace/venv/bin/python grpo_step.py --batch {sd}/batch.jsonl --adapter-in {pod_dir}/{prev} --adapter-out {pod_dir}/{new} "
            f"--lr {lr}", f"{sd}/train.log", marker), timeout=90)
        pod_poll(f"cat {marker} 2>/dev/null || true", lambda s: s.startswith("rc="), 3 * 3600)
    rc = pod(f"cat {marker}").strip()
    log = pod(f"grep GRPO_STEP_STATS {sd}/train.log || tail -30 {sd}/train.log")
    if rc != "rc=0" or "GRPO_STEP_STATS" not in log:
        raise RuntimeError(f"training step {step} failed ({rc}): {log[-800:]}")
    return json.loads(log.split("GRPO_STEP_STATS ", 1)[1].strip().splitlines()[0])


def backup(pod_dir: str, name: str, dst: Path) -> None:
    """Pod 没有持久盘：每一步的适配器（含 Adam 状态）拷回 Hetzner。"""
    dst.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(POD + [f"tar czf - -C {pod_dir}/{name} ."], capture_output=True, timeout=900)
    if p.returncode != 0:
        raise RuntimeError(f"backup of {name} failed")
    subprocess.run(["tar", "xzf", "-", "-C", str(dst)], input=p.stdout, check=True)


def run_jobs(jobs: list[tuple[str, bool]]) -> None:
    """(job, 是否开 Teacher)。没启动的启动；都等到结束；非 Teacher 的 job 有基础设施报错就补跑一次（D-062）。"""
    for job, teacher in jobs:
        if not (JOBS / job).exists():
            subprocess.run(["bash", "tools/launch_teacher_job.sh" if teacher else "tools/launch_job.sh", job], cwd=REPO, check=True)
    wait_done([j for j, _ in jobs])
    bad = [j for j, teacher in jobs if not teacher and n_infra(j)]
    if bad:
        say(f"resuming infra errors in {bad}")
        subprocess.run(["bash", "tools/resume_jobs.sh", *bad], cwd=REPO, check=True)
        wait_done(bad)


def wait_done(jobs: list[str]) -> None:
    while not all((JOBS / f"{j}.done").exists() for j in jobs):
        time.sleep(30)


def n_infra(job: str) -> int:
    return sum(1 for f in (JOBS / job).glob("*__*/result.json") if trial_reward(json.load(open(f))) is None)


def collect(jobs: list[str]) -> dict[str, list[tuple[dict, float]]]:
    g = collections.defaultdict(list)
    for job in jobs:
        for f in sorted((JOBS / job).glob("*__*/result.json")):
            r = json.load(open(f))
            rew = trial_reward(r)
            if rew is not None:
                g[r["task_name"].split("/")[-1]].append((r, rew))
    return dict(g)


def rewrite_rules(tasks: list[str], jobs: list[str], know: Path, out: Path, max_usd: float) -> tuple[dict, float]:
    """子进程里读 key、调 gpt-6-sol 写规则（本进程不碰 key）。"""
    cmd = (f"set -a; . ~/.secrets.env; set +a; PYTHONPATH=. .venv/bin/python train/synth/psp_rules.py --tasks-dir {TRAIN} "
           f"--knowledge {know} --jobs {' '.join(str(JOBS / j) for j in jobs)} --tasks {','.join(tasks)} --rules-out {out} --max-usd {max_usd:.2f}")
    r = subprocess.run(["bash", "-c", cmd], cwd=REPO, capture_output=True, text=True, timeout=3600)
    m = re.search(r"PSP_RULES_SPEND_USD ([\d.]+)", r.stdout)
    if r.returncode != 0 or not m:
        raise RuntimeError(f"rule writing failed: {(r.stdout + r.stderr)[-600:]}")
    return {x["task"]: x["rules"] for x in json.load(open(out)) if x["rules"]}, float(m.group(1))


# ---------------------------------------------------------------- 主循环
def main(a) -> None:
    rl = Path(a.rl_dir); rl.mkdir(parents=True, exist_ok=True)
    pod_dir = f"/workspace/{rl.name}"
    busy = [s for s in subprocess.run(["tmux", "ls"], capture_output=True, text=True).stdout.splitlines() if re.match(r"q(eval|pilot|roll)", s)]
    if busy and not a.force:
        raise SystemExit(f"other Harbor jobs still use vLLM: {busy}")
    for f in ("train/rl/grpo_step.py", "train/rl/serve_policy.sh", "train/ambig/sft_train.py"):
        with open(REPO / f) as fh:
            subprocess.run(POD + [f"mkdir -p /workspace/code && cat > /workspace/code/{Path(f).name}"], stdin=fh, check=True, timeout=120)
    know = rl / "knowledge.json"
    if not know.exists():
        know.write_text(json.dumps({p.name: knowledge_text(p) for p in sorted(TRAIN.iterdir()) if p.is_dir()}))
    sf = rl / "state.json"
    if sf.exists():
        state = json.load(open(sf))
    else:
        tasks = sorted(p.name for p in TRAIN.iterdir() if p.is_dir())
        order = a.only_tasks.split(",") if a.only_tasks else random.Random(0).sample(tasks, len(tasks))
        hard = set(json.load(open(HARD)))
        state = {"step": 0, "cursor": 0, "order": order, "mode": {t: HINTED if t in hard else PLAIN for t in tasks},
                 "rules": {r["task"]: r["rules"] for r in json.load(open(PILOT_RULES)) if r["rules"]},
                 "policy": f"{a.prefix}policy00", "start_time": time.time(), "api_usd": 0.0, "history": [], "args": vars(a)}
        sf.write_text(json.dumps(state, indent=1))
    p0 = f"{pod_dir}/{a.prefix}policy00"
    if pod(f"test -f {p0}/adapter_model.safetensors && echo yes || echo no").strip() != "yes":
        say("creating the step-0 adapter (LoRA B = 0, same outputs as the base model)")
        pod(f"pkill -f '[v]llm serve'; sleep 20; mkdir -p {pod_dir}; rm -f {pod_dir}/init_done.txt; " + bg(
            f"/workspace/venv/bin/python grpo_step.py --init-only --adapter-out {p0}", f"{pod_dir}/init.log", f"{pod_dir}/init_done.txt"), timeout=90)
        if pod_poll(f"cat {pod_dir}/init_done.txt 2>/dev/null || true", lambda s: s.startswith("rc="), 3600).strip() != "rc=0":
            raise RuntimeError("step-0 adapter creation failed: " + pod(f"tail -20 {pod_dir}/init.log"))
    serve(pod_dir, state["policy"])

    spent = lambda: (time.time() - state["start_time"]) / 3600 * a.usd_per_hour + state["api_usd"]   # noqa: E731
    while state["step"] < a.steps:
        k = state["step"] + 1
        if spent() > a.budget_usd:
            say(f"STOP BUDGET before step {k}: ${spent():.0f}"); break
        t0 = time.time()
        tasks, cursor = pick_tasks(state["order"], state["cursor"], a.tasks_per_step)
        sd = rl / f"step{k:02d}"; sd.mkdir(exist_ok=True)
        hinted = [t for t in tasks if state["mode"][t] == HINTED]
        teacher = a.hint_mode == "teacher"
        # 主 job（""）、Teacher job（"t"）、不带提示的试做（"p"，D-075：带提示的题每步另做 --probe-attempts 次不带提示的，不参与训练）
        split = {"": [t for t in tasks if not (teacher and t in hinted)], "t": [t for t in tasks if teacher and t in hinted],
                 "p": hinted if a.probe_attempts > 0 else []}
        attempts = {"": a.attempts, "t": a.attempts, "p": a.probe_attempts}
        conc = share_concurrency({x: len(ts) * attempts[x] for x, ts in split.items() if ts}, a.concurrency)
        rules_blocks = {t: render_block(state["rules"][t]) for t in hinted if not teacher and state["rules"].get(t)}
        jobs, probe_job = [], None
        for suffix, ts in split.items():
            if not ts:
                continue
            ds = sd / f"tasks{suffix}"
            job = f"{a.prefix}-step{k:02d}{suffix}"
            if not (JOBS / job).exists():      # job 已启动（重跑时）就不动它的题目目录：跑着的 trial 还要用
                if ds.exists():
                    shutil.rmtree(ds)
                for t in ts:
                    shutil.copytree(TRAIN / t, ds / t)
                    if suffix == "" and t in rules_blocks:
                        f = ds / t / "instruction.md"
                        f.write_text(rules_blocks[t] + f.read_text())
                (REPO / "experiments" / "configs" / f"{job}.resolved.yaml").write_text(
                    write_config(TEMPLATE.read_text(), job, ds, state["policy"], attempts[suffix], conc[suffix], str(know) if suffix == "t" else None))
            jobs.append((job, suffix == "t"))
            if suffix == "p":
                probe_job = job
        say(f"step {k}: {len(tasks)} tasks ({len(hinted)} hinted, mode {a.hint_mode}) × {a.attempts} on {state['policy']}")
        run_jobs(jobs)
        t_roll = time.time() - t0
        groups = collect([j for j, _ in jobs if j != probe_job])
        probes = collect([probe_job]) if probe_job else {}
        stats = step_stats(groups, state["mode"])
        stats["probe_passes_by_task"] = {t: [int(sum(x for _, x in g)), len(g)] for t, g in sorted(probes.items())}
        stats["probe_pass_rate"] = mean(x for g in probes.values() for _, x in g)
        rows, bstats = build_batch(groups, rules_blocks)
        (sd / "batch.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        hist = {"step": k, "policy_sampled": state["policy"], "tasks": tasks, "hinted": hinted, **stats, "batch": bstats,
                "rollout_min": round(t_roll / 60, 1)}
        if teacher:
            state["api_usd"] += teacher_usd(groups)
            hist["teacher_calls"], hist["teacher_errors"] = teacher_health(groups)
        if k == 1 and bstats["signal_groups"] < a.min_signal_groups:
            state["history"].append(hist); sf.write_text(json.dumps(state, indent=1))
            say(f"STOP NO_SIGNAL: {bstats}"); break
        new = f"{a.prefix}policy{k:02d}"
        if rows:
            t1 = time.time()
            hist["train"] = train_on_pod(pod_dir, k, state["policy"], new, sd / "batch.jsonl", a.lr)
            serve(pod_dir, new)
            backup(pod_dir, new, rl / "adapters" / new)
            hist["train_min"] = round((time.time() - t1) / 60, 1)
            state["policy"] = new
        else:
            say(f"step {k}: empty batch, policy unchanged")
        rewrite = []
        for t in tasks:
            passes, n = hist["passes_by_task"].get(t, [0, 0])
            if n == 0:
                continue
            state["mode"][t], rw = next_mode(state["mode"][t], passes, n, hist["probe_passes_by_task"].get(t, [0, 0])[0])
            if rw and not teacher:
                rewrite.append(t)
        if rewrite:
            new_rules, usd = rewrite_rules(rewrite, [j for j, _ in jobs], know, sd / "rules.json", max(0.5, a.budget_usd - spent()))
            state["rules"].update(new_rules); state["api_usd"] += usd
            hist["rules_rewritten"] = {"tasks": len(rewrite), "ok": len(new_rules), "usd": round(usd, 2)}
        state["step"], state["cursor"] = k, cursor
        hist["spent_usd"] = round(spent(), 1)
        state["history"].append(hist)
        sf.write_text(json.dumps(state, indent=1))
        with open(rl / "log.jsonl", "a") as f:
            f.write(json.dumps(hist, ensure_ascii=False) + "\n")
        tr = hist.get("train") or {}
        pr = stats["pass_rate"]   # 整步都是基础设施报错时为 None：不能让打印把已存好的一步变成崩溃
        say(f"step {k} done: pass {'—' if pr is None else f'{pr:.2f}'} (plain {stats['pass_rate_plain']}, hinted {stats['pass_rate_hinted']}) | "
            f"signal groups {bstats['signal_groups']}/{len(groups)} | batch {len(rows)} | grad {tr.get('grad_norm_before_clip')} | "
            f"lora_b {tr.get('lora_b_norm')} | probe {stats['probe_pass_rate']} | reliance {(tr.get('hint_reliance') or {}).get('mean')} | "
            f"out tokens {stats['mean_out_tokens']} | ${hist['spent_usd']}")
        why = stop_reason(state["history"], a.min_signal_groups, spent(), a.budget_usd)
        if why:
            say(f"STOP {why}"); break
    say(f"RL_LOOP_END at step {state['step']}; policy {state['policy']}; spent ${spent():.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hint-mode", choices=["rules", "teacher"], required=True, help="D-072 试点决定")
    ap.add_argument("--rl-dir", default="/root/work/rl")
    ap.add_argument("--prefix", default="rl", help="job 名 <prefix>-stepNN、策略名 <prefix>policyNN（只能小写字母和数字）")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--tasks-per-step", type=int, default=16)
    ap.add_argument("--attempts", type=int, default=8)
    ap.add_argument("--concurrency", type=int, default=32, help="一步里所有 job 合计的并发（按 trial 数分摊）")
    ap.add_argument("--probe-attempts", type=int, default=2, help="D-075：带提示的题每步另做几次不带提示的试做（只记录 + 决定下次带不带提示，不参与训练）")
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--min-signal-groups", type=int, default=4)
    ap.add_argument("--budget-usd", type=float, default=120.0)
    ap.add_argument("--usd-per-hour", type=float, default=4.6, help="Pod 单价")
    ap.add_argument("--only-tasks", default="", help="冒烟用：只在这几道题上循环")
    ap.add_argument("--force", action="store_true", help="有别的 job 在跑也启动（一般不要用）")
    main(ap.parse_args())
