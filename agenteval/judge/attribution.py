"""归因判官：渲染视图 → 调用 → 解析控制头（不合格重试一次）→ FailureLabel(source=JUDGE)。"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agenteval.judge.client import JudgeClient
from agenteval.judge.views import render_trajectory
from agenteval.schemas import FailureLabel, TrialRecord

PROMPT_DIR = Path(__file__).parent / "prompts"
LABELS = {"PREMATURE_COMPLETION": ("Verification", "MIXED"), "INSUFFICIENT_VERIFICATION": ("Verification", "MIXED"),
          "TEST_GAMING": ("Verification", "MODEL"), "SPEC_MISINTERPRETATION": ("Coherence", "MIXED"),
          "GOAL_DRIFT": ("Coherence", "MIXED"), "ACKNOWLEDGED_BUT_IGNORED": ("Coherence", "MODEL"),
          "LOOP": ("Execution", "MIXED"), "POLLING": ("Execution", "HARNESS"), "STUCK_AT_PROMPT": ("Execution", "HARNESS"),
          "TRUNCATED_READ": ("Execution", "HARNESS"), "FORMAT": ("Execution", "MIXED"), "BUDGET_EXHAUSTED": ("Execution", "MIXED"),
          "COMMAND_ERRORS": ("Execution", "MODEL"), "GAVE_UP": ("NONE", "MODEL"), "CAPABILITY": ("NONE", "MODEL"),
          "ENVIRONMENT": ("ENVIRONMENT", "ENVIRONMENT"), "TASK_UNDERSPECIFIED": ("TASK", "TASK"), "CANNOT_JUDGE": ("NONE", "UNKNOWN")}
HEAD_RE = re.compile(r"^\s*Primary:\s*([A-Z_]+)\s*$", re.M)
ONSET_RE = re.compile(r"^\s*Onset:\s*(?:step(?:_id)?\s*=?\s*|turn\s*)?(\d+|unknown)\s*$", re.M | re.I)  # claude 会写 step_id=17
CONF_RE = re.compile(r"^\s*Confidence:\s*(high|medium|low)\s*$", re.M | re.I)
SEC_RE = re.compile(r"^\s*Secondary:\s*(.+)$", re.M)
UNDER_RE = re.compile(r"^\s*Underspecification:\s*(.+)$", re.M)


def prompt_version(name: str = "attribution_v2.txt") -> tuple[str, str]:
    text = (PROMPT_DIR / name).read_text()
    return name, hashlib.sha256(text.encode()).hexdigest()[:8]


def parse(text: str) -> dict | None:
    m1, m2, m3 = HEAD_RE.search(text), ONSET_RE.search(text), CONF_RE.search(text)
    if not (m1 and m2 and m3) or m1.group(1) not in LABELS:
        return None
    sec = SEC_RE.search(text)
    secondary = [s.strip() for s in (sec.group(1) if sec else "none").split(",") if s.strip() and s.strip().lower() != "none" and s.strip() in LABELS]
    onset = None if m2.group(1).lower() == "unknown" else int(m2.group(1))
    under = UNDER_RE.search(text)
    return {"primary": m1.group(1), "onset": onset, "confidence": m3.group(1).lower(), "secondary": secondary,
            "underspecification": (under.group(1).strip() if under else "none"), "raw": text}


def judge_trial(client: JudgeClient, t: TrialRecord, instruction: str | None, prompt_name: str = "attribution_v2.txt", blind: bool = False,
                tests: str | None = None, votes: int = 1, full: dict | None = None) -> list[FailureLabel]:
    system = (PROMPT_DIR / (prompt_name if not blind else "attribution_v1.txt")).read_text()
    user = render_trajectory(t, instruction, blind=blind, tests=tests, full=full)
    if votes > 1:   # 多数投票：第 1 票走缓存，其余票绕过缓存（同一提示的独立采样）
        results = []
        for k in range(votes):
            r = client.complete(system, user, use_cache=(k == 0))
            pr = parse(r)
            if pr is None:
                repair = ("Your previous answer did not follow the required format. Rewrite it so the first three non-empty lines are exactly "
                          "'Primary: <label>', 'Onset: <step_id or unknown>', 'Confidence: high|medium|low', keeping the same judgment.\n\nPrevious answer:\n" + r)
                r = client.complete(system, user + "\n\n" + repair, use_cache=False); pr = parse(r)
            if pr is not None: results.append(pr)
        if not results:
            _, ver = prompt_version(prompt_name)
            return [FailureLabel("CANNOT_JUDGE", True, "BOOLEAN", "JUDGE", "NONE", "UNKNOWN", 0.0, "judge output unparseable", None, f"judge:{client.model}:{prompt_name}@{ver}")]
        from collections import Counter
        tally = Counter(p["primary"] for p in results); top, n = tally.most_common(1)[0]
        winners = [p for p in results if p["primary"] == top]
        parsed = dict(winners[0]); parsed["raw"] = f"[votes: {dict(tally)}]\n" + winners[0]["raw"]
        parsed["confidence"] = "high" if n == len(results) else ("medium" if n > len(results) / 2 else "low")
        if n <= len(results) / 2 and len(tally) == len(results):   # 三票三样 → 不确定
            parsed["primary"] = "CANNOT_JUDGE"; parsed["confidence"] = "low"
        onsets = [p["onset"] for p in winners if p["onset"] is not None]
        parsed["onset"] = sorted(onsets)[len(onsets) // 2] if onsets else None
    else:
        raw = client.complete(system, user)
        parsed = parse(raw)
    if votes <= 1 and parsed is None:  # 格式修复重试一次（LongHorizon build_role_auditor_format_repair_prompt 的做法）
        repair = ("Your previous answer did not follow the required format. Rewrite it so the first three non-empty lines are exactly "
                  "'Primary: <label>', 'Onset: <step_id or unknown>', 'Confidence: high|medium|low', keeping the same judgment.\n\n"
                  "Previous answer:\n" + raw)
        raw = client.complete(system, user + "\n\n" + repair, use_cache=False)
        parsed = parse(raw)
    _, ver = prompt_version(prompt_name)
    cfg = f"judge:{client.model}:{prompt_name}@{ver}"
    conf_map = {"high": 0.9, "medium": 0.7, "low": 0.5}
    if parsed is None:
        return [FailureLabel("CANNOT_JUDGE", True, "BOOLEAN", "JUDGE", "NONE", "UNKNOWN", 0.0, "judge output unparseable twice", None, cfg)]
    tb, blame = LABELS[parsed["primary"]]
    labs = [FailureLabel("primary_failure", parsed["primary"], "CATEGORICAL", "JUDGE", tb, blame, conf_map[parsed["confidence"]],
                         parsed["raw"][:2000], parsed["onset"], cfg)]
    for s in parsed["secondary"]:
        tb2, bl2 = LABELS[s]
        labs.append(FailureLabel(s, True, "BOOLEAN", "JUDGE", tb2, bl2, 0.5, "secondary label from judge", parsed["onset"], cfg))
    if parsed["underspecification"].lower() != "none":
        labs.append(FailureLabel("judge_underspecification_note", parsed["underspecification"][:500], "TEXT", "JUDGE", "TASK", "TASK", 0.5,
                                 "judge noted a missing requirement in the instruction", None, cfg))
    return labs
