"""提议：让强模型根据 harness 队列提出候选改动；这里只放纯函数（拼提示、解析、校验），调用模型在 tools/loop_cycle.py。

模型的输出不可信，进版本记录前必须过三道检查：
1. 改动落在 auto 范围内、类型和取值合法、依赖满足（scope.validate_change）；
2. 预注册完整：目标毛病、机制指标（必须是观察里有的字段）、机制和通过率的预测、证伪条件；
3. 不是已有版本（指纹相同 = 同一个 harness）。
需要写代码的想法只能进 review 提案，不会自动生效。
文字类候选（text 档：提醒、skill，D-089）可以进版本记录，但文字先过 notes.screen_note、再由人批准（Registry.approve_text）才能评测。

提示分两块（D-089）：可改写的 playbook（规则和经验，experiments/loop/playbooks/P*.md；提议模型自己改写 P0 → P1 就是这里的递归）
和固定的 FORMAT（输出格式与数量上限，代码要解析，不许改）。硬规则（范围、泄题过滤、人批文字）都在代码里强制，playbook 改不掉。
"""
from __future__ import annotations

import json
import re
from typing import Any

from agenteval.loop.scope import scope_table

# 观察行里可作机制指标的字段（tools/loop_cycle.observe_trial 生成）；全部是越低越好
METRICS = {
    "n_parse_err": "format-error turns per trial", "json_loop_end": "ends stuck in format errors (0/1)",
    "turns": "agent turns per trial", "tokens_in": "input tokens per trial", "minutes": "agent wall-clock minutes per trial",
    "timeout": "hit the agent time limit (0/1)", "turn_cap": "hit the turn limit (0/1)", "polling_turns": "empty-wait turns per trial",
    "echo_theater": "printed 'done' with echo instead of checking (0/1)", "false_success": "claimed success while admitting failure (0/1)",
    "no_run_before_claim": "claimed completion with no run after the last edit (0/1)", "cnf": "used a command missing from the image (0/1)",
    "append_turns": "turns that append to a file one line at a time with echo/printf >> (per trial)",
    "turns_after_gate": "turns spent after the completion gate bounced the first claim (per trial)",
}

SYSTEM = ("You improve the harness (the control program around a fixed LLM) of a terminal coding agent. "
          "You only propose changes; a statistical gate decides. Be concrete, conservative, and honest about weak evidence.")

INSTRUCTIONS = """Propose harness changes for the next evaluation round.

Rules:
- AUTO candidates may only change options whose tier is "auto" in the scope table, within the allowed values, respecting "requires".
  Never touch frozen options. Each candidate is ONE configuration relative to the current version (it may change several options).
- Prefer mechanisms that do not consume model turns: on a hard time limit, prompts that make the model do extra verification have
  cost more than they gained (see history: grader_check, auditor, self_check).
- Use the history. Do not re-propose a change that already failed for the same reason unless the model or the failure profile
  is different here, and say why in "why_now".
- Every AUTO candidate needs a pre-registration: target_mode (one of the harness targets), mechanism_metric (one of the metric keys),
  predicted_mechanism_change (direction and rough size), predicted_pass_change (pp range; "0" is allowed for efficiency changes),
  falsified_if (what result would show the idea is wrong).
- Ideas that need new code or new prompt text go to REVIEW proposals (a human will decide), never to AUTO candidates.
- Also list obvious changes you considered and rejected, with the reason.
- At most {k_auto} AUTO candidates and {k_review} REVIEW proposals. Fewer is fine if the evidence is weak.

Return ONLY a JSON object:
{{"auto_candidates": [{{"changes": {{"option": value}}, "target_mode": "...", "mechanism": "one sentence: how it reduces the target",
   "mechanism_metric": "...", "predicted_mechanism_change": "...", "predicted_pass_change": "...", "falsified_if": "...",
   "why_now": "...", "risk": "..."}}],
  "review_proposals": [{{"title": "...", "target_mode": "...", "what_to_build": "...", "why": "...", "how_to_test": "...", "risk": "..."}}],
  "rejected_ideas": [{{"idea": "...", "why": "..."}}]}}
"""


def build_prompt(current: dict[str, Any], targets: list[dict[str, Any]], history: list[dict[str, Any]], context: dict[str, Any],
                 k_auto: int = 4, k_review: int = 3, previous: list[dict[str, Any]] | None = None,
                 playbook: str | None = None) -> tuple[str, str]:
    """返回 (system, user)。targets 来自 reflect 的 harness 队列；context 写清模型、开发集、预算等；
    previous = 版本记录里已有的候选（状态、改动、撤下 / 否决的理由），免得提议模型重复已经被拒的配置。
    playbook = 规则那一块的文字（P0、P1 …）；不给就用第 1 轮的 INSTRUCTIONS（只有 auto 档）。"""
    slim_targets = [{k: t.get(k) for k in ("mode", "label", "among", "prior", "evidence", "levers", "n", "denominator", "rate",
                                            "share_of_failures", "n_tasks", "tried")} for t in targets]
    for t in slim_targets:
        t["rate"] = round(t["rate"] or 0, 3)
        t["share_of_failures"] = round(t["share_of_failures"] or 0, 3)
    slim_history = [{k: h.get(k) for k in ("id", "change", "switches", "model", "pass_delta_pp", "ci_low", "ci_high",
                                            "mechanism_effects", "cost_effects", "manual_verdict")} for h in history]
    rules = (playbook.strip() + "\n\n" + FORMAT.format(k_auto=k_auto, k_review=k_review)) if playbook \
        else INSTRUCTIONS.format(k_auto=k_auto, k_review=k_review)
    user = "\n\n".join([
        rules,
        "CONTEXT:\n" + json.dumps(context, ensure_ascii=False, indent=1),
        "CURRENT VERSION (effective options):\n" + json.dumps(current, ensure_ascii=False, indent=1),
        "SCOPE TABLE:\n" + json.dumps(scope_table(), ensure_ascii=False, indent=1),
        "METRIC KEYS (for mechanism_metric):\n" + json.dumps(METRICS, ensure_ascii=False, indent=1),
        "HARNESS TARGETS observed on the development set (most important first):\n" + json.dumps(slim_targets, ensure_ascii=False, indent=1),
        "HISTORY of harness changes already tested in this project (with outcomes):\n" + json.dumps(slim_history, ensure_ascii=False, indent=1),
        "PREVIOUS CANDIDATES in this loop (re-proposing the same configuration is rejected as a duplicate):\n"
        + json.dumps(previous or [], ensure_ascii=False, indent=1),
    ])
    return SYSTEM, user


# 固定的输出格式（不属于 playbook，提议模型改写 playbook 时改不到这里）
FORMAT = """Limits: at most {k_auto} candidates and {k_review} REVIEW proposals.

Return ONLY a JSON object:
{{"auto_candidates": [{{"changes": {{"option": value}}, "target_mode": "...", "mechanism": "one sentence: how it reduces the target",
   "mechanism_metric": "...", "predicted_mechanism_change": "...", "predicted_pass_change": "...", "falsified_if": "...",
   "why_now": "...", "risk": "..."}}],
  "review_proposals": [{{"title": "...", "target_mode": "...", "what_to_build": "...", "why": "...", "how_to_test": "...", "risk": "..."}}],
  "rejected_ideas": [{{"idea": "...", "why": "..."}}]}}
For text-tier options the value is a list, for example
  "custom_notes": [{{"trigger": "<a trigger from the menu>", "text": "<one sentence>"}}]
  "skills": [{{"name": "lowercase-with-hyphens", "description": "<one line: when to open it>", "body": "<the how-to>"}}]
"""


ANSWER_KEYS = ("auto_candidates", "review_proposals", "rejected_ideas")


def parse_response(text: str) -> dict[str, Any]:
    """从模型回复里取出答案对象：第一个含 auto_candidates / review_proposals / rejected_ideas 的完整 JSON 对象
    （容忍代码块和前后废话）。回复被截断时不会把里面某个候选当成答案。取不到 → 抛 ValueError。"""
    t = re.sub(r"```(?:json)?", "", text or "")
    start = t.find("{")
    while start != -1:
        depth, in_str, esc, end = 0, False, False, None
        for i in range(start, len(t)):
            c = t[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            break                                              # 没有闭合：回复被截断
        try:
            obj = json.loads(t[start:end + 1])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and any(k in obj for k in ANSWER_KEYS):
            return obj
        start = t.find("{", end + 1 if obj is not None else start + 1)
    raise ValueError("no proposer answer object (with auto_candidates / review_proposals) found in the response")


def prereg_of(c: dict[str, Any]) -> dict[str, Any]:
    return {k: c.get(k) for k in ("target_mode", "mechanism", "mechanism_metric", "predicted_mechanism_change",
                                  "predicted_pass_change", "falsified_if", "why_now", "risk")}


def check_candidate(c: Any, target_ids: set[str]) -> list[str]:
    """预注册层面的检查（范围和重复由 Registry.propose 查）。模型输出不可信：任何类型都不能让它崩溃。"""
    if not isinstance(c, dict):
        return ["candidate is not a JSON object"]
    errs = []
    if not isinstance(c.get("changes"), dict) or not c["changes"]:
        errs.append("changes must be a non-empty object")
    tm, mm = c.get("target_mode"), c.get("mechanism_metric")
    if not isinstance(tm, str) or tm not in target_ids:
        errs.append(f"target_mode {tm!r} is not one of the harness targets {sorted(target_ids)}")
    if not isinstance(mm, str) or mm not in METRICS:
        errs.append(f"mechanism_metric {mm!r} is not an observed metric")
    for k in ("predicted_mechanism_change", "predicted_pass_change", "falsified_if"):
        v = c.get(k)
        if v is None or isinstance(v, (list, dict)) or (isinstance(v, str) and not v.strip()):
            errs.append(f"missing {k}")                         # 数字 0 是合法的预测
    return errs


_DEC = re.compile(r"\b(decreas\w*|down|lower\w*|fewer|less|reduc\w*|drop\w*|cut\w*|fall\w*|fell|shrink\w*|declin\w*|minus)\b"
                  r"|下降|减少|降低|[-−]\s*\d")
_INC = re.compile(r"\b(increas\w*|higher|rise[sn]?|rising|rose|grow\w*|rais\w*)\b|上升|增加|升高")


def mechanism_direction(c: dict[str, Any]) -> str:
    """预测里写的是降还是升：出现任何"降"的说法就按降；只有"升"的说法才按升；都没有按降（METRICS 都是越低越好）。"""
    s = str(c.get("predicted_mechanism_change") or "").lower()
    if _DEC.search(s):
        return "decrease"
    if _INC.search(s):
        return "increase"
    return "decrease"


def candidate_texts(changes: Any) -> list[str]:
    """候选里会被 Qwen 看到的文字（提醒原文、skill 的名字 / 简介 / 正文），逐段交给 notes.screen_note（D-089）。"""
    if not isinstance(changes, dict):
        return []
    out = []
    for n in changes.get("custom_notes") or []:
        if isinstance(n, dict) and isinstance(n.get("text"), str):
            out.append(n["text"])
    for sk in changes.get("skills") or []:
        if isinstance(sk, dict):
            out += [str(sk.get(k, "")) for k in ("name", "description", "body") if sk.get(k)]
    return out
