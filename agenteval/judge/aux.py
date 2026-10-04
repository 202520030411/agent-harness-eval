"""便宜判官：指令清晰度（0–3 两维度）与 TB 十类动作编码（2609.20804 Fig.42 / Table 9）。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from agenteval.judge.client import JudgeClient
from agenteval.schemas import TrialRecord

PROMPT_DIR = Path(__file__).parent / "prompts"
PHASE = {"I": "Understand", "S": "Understand", "C": "Write", "M": "Write", "E": "Environment",
         "X": "Verify", "T": "Verify", "V": "Verify", "N": "Other", "W": "Wait", "G": "Other"}


def rate_clarity(client: JudgeClient, task_name: str, instruction: str) -> dict:
    system = (PROMPT_DIR / "clarity_v1.txt").read_text()
    raw = client.complete(system, f"TASK: {task_name}\n\nINSTRUCTION:\n{instruction.strip()}")
    def grab(k):
        m = re.search(rf"^\s*{k}:\s*(.+)$", raw, re.M); return m.group(1).strip() if m else None
    def num(v):
        try: return int(re.search(r"[0-3]", v or "").group(0))
        except Exception: return None
    return {"task": task_name, "intent_clarity": num(grab("intent_clarity")), "target_certainty": num(grab("target_certainty")),
            "missing": grab("missing"), "interpretations_at_risk": grab("interpretations_at_risk"), "raw": raw[:1500]}


def _actions_block(t: TrialRecord, max_obs: int = 300) -> tuple[str, int]:
    lines, n = [], 0
    for s in t.agent_steps:
        lines.append(f"-- Turn step_id={s.step_id} --")
        for k in s.keystrokes:
            n += 1
            lines.append(f"[{n}] KEYSTROKES: " + (repr(k[:400]) if k.strip() else "<empty: wait>"))
        obs = s.observation_text.strip()
        if obs:
            lines.append("   OUTPUT: " + (obs[:max_obs] + (" [...]" if len(obs) > max_obs else "")).replace("\n", " | "))
    return "\n".join(lines), n


def encode_actions(client: JudgeClient, t: TrialRecord) -> dict:
    block, n = _actions_block(t)
    if n == 0:
        return {"trial_id": t.trial_id, "task": t.task_name, "labels": [], "phases": []}
    tmpl = (PROMPT_DIR / "actions_v1.txt").read_text()
    user = tmpl.replace("{actions_block}", block).replace("{n_actions}", str(n))
    raw = client.complete("You label coding-agent actions. Output only JSON.", user)
    labels = []
    try:
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1])
        for i in range(1, n + 1):
            v = data.get(str(i)) or data.get(f"Turn{i}") or {}
            lab = (v.get("label") or "G").strip().upper()[:1]
            labels.append(lab if lab in PHASE else "G")
    except Exception:
        labels = ["?"] * n
    return {"trial_id": t.trial_id, "task": t.task_name, "passed": t.passed, "n_actions": n, "labels": labels,
            "phases": [PHASE.get(l, "?") for l in labels]}


def termination_stats(rows: list[dict]) -> dict:
    """终止阶段表（2609.20804 Table 12 的简化版）：没写过代码就停 / 停在 Understand / 写了但没解出。"""
    out = {"n": 0, "wo_code": 0, "at_understand": 0, "wrote_unresolved": 0, "passed": 0}
    for r in rows:
        if not r.get("labels"): continue
        out["n"] += 1
        wrote = any(l in ("C", "M") for l in r["labels"])
        if r.get("passed"):
            out["passed"] += 1; continue
        if not wrote:
            out["wo_code"] += 1
            if all(l in ("I", "S", "N", "W", "G") for l in r["labels"]): out["at_understand"] += 1
        else:
            out["wrote_unresolved"] += 1
    return out
