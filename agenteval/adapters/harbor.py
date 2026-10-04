"""Harbor jobs 目录 → TrialRecord。

读取每个 trial 目录的 result.json（reward / exception / 计时 / token 汇总）和
agent/trajectory.json（ATIF：逐轮的 tool_calls、observation、metrics）。
只读文件，不做任何判断；判断在 attribute/ 里。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agenteval.schemas import Step, TrialRecord

TRUNCATION_MARK = "[... output limited to"
PARSE_ERROR_MARK = "Previous response had parsing errors"


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _steps_from_atif(traj: dict) -> list[Step]:
    steps: list[Step] = []
    for raw in traj.get("steps", []):
        st = Step(step_id=raw.get("step_id", len(steps) + 1), source=raw.get("source", ""), message=raw.get("message") or "")
        for tc in raw.get("tool_calls") or []:
            fn = tc.get("function_name")
            args = tc.get("arguments") or {}
            if fn == "bash_command":
                st.keystrokes.append(str(args.get("keystrokes", "")))
                st.durations.append(float(args.get("duration", 0) or 0))
            elif fn == "mark_task_complete":
                st.claimed_complete = True
        obs = raw.get("observation") or {}
        contents = [r.get("content") or "" for r in obs.get("results") or [] if isinstance(r, dict)]
        st.observation_text = "\n".join(c for c in contents if c)
        st.truncated = TRUNCATION_MARK in st.observation_text
        st.parse_error = st.observation_text.startswith(PARSE_ERROR_MARK)
        extra = raw.get("extra") or {}
        st.compaction_boundary = bool((extra.get("context_management") or {}).get("type") == "compaction")
        m = raw.get("metrics") or {}
        st.prompt_tokens = int(m.get("prompt_tokens") or 0)
        st.completion_tokens = int(m.get("completion_tokens") or 0)
        st.cached_tokens = int(m.get("cached_tokens") or 0)
        st.cost = float(m.get("cost_usd") or 0.0)
        st.has_reasoning = bool(raw.get("reasoning_content"))
        steps.append(st)
    return steps


def load_trial(trial_dir: Path, job_name: str | None = None, config_id: str | None = None) -> TrialRecord:
    trial_dir = Path(trial_dir)
    res = json.loads((trial_dir / "result.json").read_text())
    traj_path = trial_dir / "agent" / "trajectory.json"
    traj = json.loads(traj_path.read_text()) if traj_path.exists() else {"steps": []}

    ar = res.get("agent_result") or {}
    md = ar.get("metadata") or {}
    vr = res.get("verifier_result") or {}
    rewards = vr.get("rewards") or {}
    reward = rewards.get("reward")
    reward = float(reward) if reward is not None else None
    exc = res.get("exception_info") or {}
    exc_type = exc.get("exception_type")
    exc_msg = exc.get("exception_message")

    # status：基础设施失败先判（不变量 3）；agent 超时是预算问题，不算基础设施
    if exc_type:
        et = exc_type.lower()
        if "timeout" in et and "agent" in et:
            status = "agent_timeout"
        elif res.get("agent_execution") is None:
            status = "setup_failed"
        elif "verifier" in et:
            status = "verifier_error"
        else:
            status = "agent_error"
    elif reward is None:
        status = "verifier_error"
    else:
        status = "ok"

    ae = res.get("agent_execution") or {}
    t0, t1 = _iso(ae.get("started_at")), _iso(ae.get("finished_at"))
    wall = (t1 - t0).total_seconds() if t0 and t1 else None

    agent_info = res.get("agent_info") or {}
    model = (agent_info.get("model_info") or {}).get("name") or ""
    trial_name = res.get("trial_name") or trial_dir.name
    attempt = 0
    # Harbor 的 trial 目录名形如 <task>__<id>；同题多次 attempt 按目录顺序编号，由 load_job 补
    return TrialRecord(
        trial_id=trial_name,
        task_name=(res.get("task_name") or trial_name.split("__")[0]).split("/")[-1],   # 去掉 dataset 前缀，与 task_list.txt 一致
        config_id=config_id or f"{agent_info.get('name','?')}@{model}",
        attempt=attempt,
        job_name=job_name or trial_dir.parent.name,
        agent_name=agent_info.get("name") or "",
        model_name=model,
        reward=reward,
        status=status,
        exception_type=exc_type,
        exception_message=(exc_msg or "")[:500] or None,
        n_episodes=int(md.get("n_episodes") or 0),
        summarization_count=int(md.get("summarization_count") or 0),
        wall_clock_sec=wall,
        tokens_in=int(ar.get("n_input_tokens") or 0),
        tokens_out=int(ar.get("n_output_tokens") or 0),
        tokens_cached=int(ar.get("n_cache_tokens") or 0),
        cost=float(ar.get("cost_usd") or 0.0),
        steps=_steps_from_atif(traj),
        metadata={"api_request_times_msec": md.get("api_request_times_msec") or [], "patched": md.get("patched"),
                  "verifier_stdout_tail": _tail(trial_dir / "verifier" / "test-stdout.txt", 3000)},
    )


def _tail(path: Path, n: int) -> str | None:
    if not path.exists():
        return None
    txt = path.read_text(errors="replace")
    return txt[-n:] if len(txt) > n else txt


def load_job(job_dir: Path, config_id: str | None = None) -> list[TrialRecord]:
    job_dir = Path(job_dir)
    trials: list[TrialRecord] = []
    for d in sorted(p for p in job_dir.iterdir() if p.is_dir() and (p / "result.json").exists()):
        trials.append(load_trial(d, job_name=job_dir.name, config_id=config_id))
    # attempt 编号：同题按目录顺序 0,1,2…
    seen: dict[str, int] = {}
    for t in trials:
        t.attempt = seen.get(t.task_name, 0)
        seen[t.task_name] = t.attempt + 1
    return trials
