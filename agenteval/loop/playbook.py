"""提议模型改写自己的 playbook（D-089，闭环里"递归"的那一层）：拿它过去的预测和实际结果，改写规则那一块（P0 → P1 → P2）。

这里只放纯函数（整理证据、拼提示、解析、检查）；调用模型在 tools/loop_cycle.py rewrite-playbook。
- 证据只来自版本记录：每个候选的预注册（预测）和结果（门的决定、通过率、机制指标、被撤下的理由）。不给任何轨迹或题目内容。
- 改得了的只有 playbook；输出格式（propose.FORMAT）、范围、泄题过滤、人批文字都在代码里，改不到。
- 新 playbook 有长度上限，要过泄题检查（和某道题连续 6 个词相同、出现只属于少数题的标识符）；第一次改写由人批准后才用。
"""
from __future__ import annotations

import difflib
import json
import re
from typing import Any

MAX_WORDS = 700
HARD_RULES = [
    "the output format and the limits on the number of candidates (fixed in code)",
    "which options exist and their allowed values (the scope table, enforced in code)",
    "text is screened for task content and grading words, and a human approves it before evaluation (enforced in code)",
    "the statistical gate decides; candidates cannot change how they are evaluated",
]


def evidence(versions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """每个候选一条：谁提的、改了什么、预测了什么、结果如何。只保留数字和理由，不带任何轨迹。"""
    out = []
    for vid, v in versions.items():
        if not v.get("parent"):
            continue
        pr = v.get("prereg") or {}
        row = {"version": vid, "proposed_by": v.get("source", ""), "change": v.get("change"), "status": v.get("status"),
               "prediction": {k: pr.get(k) for k in ("target_mode", "mechanism_metric", "predicted_mechanism_change",
                                                     "predicted_pass_change", "falsified_if")}}
        evs = [e for e in v.get("evaluations") or [] if e.get("decision") != "INVALID"]
        if evs:
            e = evs[-1]
            row["outcome"] = {"decision": e.get("decision"), "reasons": e.get("reasons"), "pass_pp": e.get("pass"),
                              "mechanism": e.get("mechanism"), "efficiency": e.get("efficiency")}
            if v.get("notes"):                      # 事后的更正（比如 D-088：判它的护栏本身有问题）也是证据
                row["outcome"]["later_notes"] = v["notes"]
        elif v.get("notes"):
            row["outcome"] = {"decision": v.get("status"), "reasons": v.get("notes")}
        else:
            row["outcome"] = {"decision": "not evaluated yet"}
        out.append(row)
    return out


SYSTEM = ("You maintain the playbook that guides proposals of harness changes for a terminal coding agent. You learn from how past "
          "predictions compared with measured outcomes.")

TEMPLATE = """Below is the current playbook (the rules part of the proposer prompt), followed by every candidate proposed so far:
what was predicted and what happened. Rewrite the playbook so that future proposals are better calibrated and more likely to
produce real, measurable improvements.

Constraints:
- Keep what worked; change only what the evidence supports. Each change must cite the candidates (version ids) that motivate it.
- At most {max_words} words. Plain rules and checklists, no examples copied from any task.
- You cannot change these, they are enforced in code: {hard_rules}.

CURRENT PLAYBOOK:
{playbook}

EVIDENCE (predictions vs outcomes):
{evidence}

Return ONLY a JSON object:
{{"playbook": "<the full new playbook text>",
  "changes": [{{"change": "<what you changed>", "evidence": ["<version ids>"], "expected_effect": "<what should improve>"}}]}}"""


def build_prompt(playbook: str, ev: list[dict[str, Any]]) -> tuple[str, str]:
    return SYSTEM, TEMPLATE.format(max_words=MAX_WORDS, hard_rules="; ".join(HARD_RULES), playbook=playbook.strip(),
                                   evidence=json.dumps(ev, ensure_ascii=False, indent=1))


def parse(text: str) -> dict[str, Any]:
    t = re.sub(r"```(?:json)?", "", text or "")
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("no JSON object")
    obj = json.loads(m.group(0))
    if not isinstance(obj.get("playbook"), str) or not obj["playbook"].strip():
        raise ValueError("missing playbook text")
    if not isinstance(obj.get("changes"), list) or not obj["changes"]:
        raise ValueError("missing the list of changes")
    return obj


def check(new: str, ev: list[dict[str, Any]], changes: list[dict], screen) -> list[str]:
    """新 playbook 的硬检查：长度、每条改动都引用了真实存在的候选、过泄题检查（screen = 已绑定题目文字的 screen_note）。"""
    probs = []
    words = len(re.findall(r"\S+", new))
    if words > MAX_WORDS:
        probs.append(f"too long: {words} words (max {MAX_WORDS})")
    known = {e["version"] for e in ev}
    for c in changes:
        cited = set(c.get("evidence") or []) if isinstance(c, dict) else set()
        if not cited or not cited <= known:
            probs.append(f"change {str(c)[:80]!r} cites {sorted(cited)}, not a subset of the known candidates {sorted(known)}")
    # 版本编号（v0、c04、v0+c04）是按要求引用的证据，不算"只属于少数题的标识符"
    probs += [p for p in screen(new) if p.startswith("shares a 6-word")
              or (p.startswith("uses an identifier") and not _VERSION_ID.search(p))]
    return probs


_VERSION_ID = re.compile(r"'(v\d+|c\d+|v\d+\+c\d+)'$")


def unified_diff(old: str, new: str, a: str = "P0", b: str = "P1") -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=a, tofile=b))
