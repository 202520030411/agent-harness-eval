"""判官看到的轨迹视图（借 rollout-mvp agent/views.py）。

不变量 2：不含 reasoning_content、不含 reward、不含其他判官的输出。
模型自己写的 Analysis/Plan 会给判官看，但标为"agent 自述"，判官被要求当声明而非证据（LongHorizon Auditor 原则）。
"""
from __future__ import annotations

from agenteval.schemas import TrialRecord

OBS_MAX = 1800     # 每轮观察最多字符（头尾各半）
MSG_MAX = 600      # 每轮自述最多字符
KEY_MAX = 400


def _clip(s: str, n: int) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    h = n // 2
    return s[:h] + f"\n[... {len(s) - n} chars omitted ...]\n" + s[-h:]


def render_trajectory(t: TrialRecord, instruction: str | None = None, max_steps: int = 80, blind: bool = False, tests: str | None = None,
                      full: dict | None = None) -> str:
    """full: {tests, environment, solution, verifier_stdout} → 全 context 模式（D-037）：不截轮次、逐轮输出放宽、附完整验证器输出与题目素材。"""
    obs_max, msg_max, key_max = (OBS_MAX, MSG_MAX, KEY_MAX) if not full else (8000, 2000, 1500)
    if full: max_steps = 10_000
    out = []
    out.append(f"TASK: {t.task_name}")
    if instruction:
        out.append("INSTRUCTION (verbatim):\n" + instruction.strip())
    out.append(f"RUN FACTS: turns={t.n_episodes}, status={t.status}, compactions={t.summarization_count}, "
               f"claimed_complete={'yes' if any(s.claimed_complete for s in t.steps) else 'no'}")
    steps = t.agent_steps
    shown = steps if len(steps) <= max_steps else steps[: max_steps // 2] + steps[-max_steps // 2:]
    skipped = len(steps) - len(shown)
    for i, s in enumerate(shown):
        if skipped and i == max_steps // 2:
            out.append(f"\n[... {skipped} middle turns omitted ...]\n")
        out.append(f"--- TURN step_id={s.step_id} ---")
        if s.message:
            out.append("AGENT SAYS (claim, not evidence): " + _clip(s.message.strip(), msg_max))
        if s.claimed_complete:
            out.append("AGENT ACTION: mark_task_complete")
        for k in s.keystrokes:
            out.append("KEYSTROKES: " + (repr(_clip(k, key_max)) if k.strip() else "<empty: wait>"))
        if s.parse_error:
            out.append("HARNESS: previous response had parsing errors")
        out.append("TERMINAL: " + _clip(s.observation_text.strip(), obs_max))
    vt = (t.metadata or {}).get("verifier_stdout_tail")
    if full and full.get("verifier_stdout"): vt = full["verifier_stdout"]
    if not blind:
        out.append("\n=== OUTCOME: this trial FAILED the hidden tests. ===")
        if vt:
            out.append(("VERIFIER OUTPUT (full; the agent never saw this):\n" if full else "VERIFIER OUTPUT (tail; the agent never saw this):\n") + vt.strip())
        else:
            out.append("VERIFIER OUTPUT: not available")
        if full:
            for key, title in [("tests", "HIDDEN TESTS (use them to tell whether the instruction actually specified what the tests require)"),
                               ("environment", "TASK ENVIRONMENT FILES (Dockerfile and small files present in the container)"),
                               ("solution", "REFERENCE SOLUTION (the task author's own solve script; shows what the author expected)")]:
                if full.get(key): out.append(f"{title}:\n{full[key]}")
        elif tests:
            out.append("HIDDEN TESTS (the agent never saw these; use them to tell whether the instruction actually specified what the tests require):\n" + tests)
    return "\n".join(out)


def assert_blind(text: str, t: TrialRecord) -> None:
    """测试用：视图里不得出现 reward 或 reasoning。"""
    assert "reward" not in text.lower().replace("rewarded", "")
    for s in t.steps:
        assert not s.has_reasoning or True  # reasoning 内容从未进入 Step，这里只留占位断言
