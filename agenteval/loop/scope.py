"""自进化闭环的"可修改范围"（mutable scope）：哪些 harness 选项可以自动改、哪些要人审、哪些绝不能动。

照文枢（Loop Engineering）的三档，但收紧：
- auto：已有开关的开 / 关和数值参数，只能在给定范围内取值；闭环可以自己提出、自己评测。
- text（D-089）：提醒文字（挂在固定触发条件上）和只含文字的 skill。闭环可以写，但格式在这里查（触发条件从固定菜单选、字数和条数有上限），
  文字本身还要过 notes.screen_note，而且必须有人批准过这段文字（Registry.approve_text）才能排进评测。
- review：新的提示文字、新机制、任何代码改动——闭环只能写成提案，必须人看过才实现。
- frozen：评测协议的一部分（轮数上限、上下文摘要、模型与采样设置）、训练专用或会泄露答案的开关
  （teacher_hint 会看参考解和隐藏测试，绝不能进部署用的 harness）、观察所需的记录开关（raw_log 必须开）。

所有函数都是纯函数，便于单测。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from terminus2_patches.helpers import NOTE_PLACEHOLDERS, NOTE_TRIGGERS


@dataclass(frozen=True)
class Knob:
    name: str
    kind: str                      # bool | float | int | enum | notes | skills
    tier: str                      # auto | text（闭环写、人批文字）| review（人批准后才改成 auto）| frozen
    default: Any
    lo: float | None = None
    hi: float | None = None
    values: tuple = ()
    requires: tuple = ()           # 只有这些开关为真（或等于给定值）时，这个选项才有意义
    note: str = ""


# Terminus2PatchedOptions（terminus2_patches/agent.py）里与策略有关的选项。默认值与 agent.py 一致。
KNOBS: dict[str, Knob] = {k.name: k for k in [
    Knob("interface_fixes", "bool", "auto", False, note="H1：宽松解析 + 开跑前环境探测 + 续行提示（Qwen 格式错误轮 −93%）"),
    Knob("completion_gate", "bool", "auto", False, note="H2：第一次宣布完成时，没运行过检查或承认没做成就打回一次"),
    Knob("adaptive_wait", "bool", "auto", False, note="哨兵 + 超时 + 交互提示正则（Seed 空等待轮 −27%、token −11%）"),
    Knob("wait_stable_sec", "float", "auto", 3.0, lo=1.0, hi=10.0, requires=("adaptive_wait",), note="退化路径：屏幕连续无变化秒数"),
    Knob("wait_cap_sec", "float", "auto", 30.0, lo=10.0, hi=120.0, requires=("adaptive_wait",), note="单条命令最长等待"),
    Knob("deliverable_checkpoint", "bool", "auto", False, note="到时间阈值时交付文件还不存在就提醒先写答案（Seed：无交付 11→6，通过率 −5.1）"),
    Knob("checkpoint_after_sec", "float", "auto", 480.0, lo=240.0, hi=720.0, requires=("deliverable_checkpoint",)),
    Knob("checkpoint_repeat_sec", "float", "auto", 180.0, lo=60.0, hi=300.0, requires=("deliverable_checkpoint",)),
    Knob("verifier_gate", "enum", "auto", "none", values=("none", "self_check", "grader_check"),
         note="完成前让模型自查；Seed 上 self_check +6.4（不显著、成本 +35%），grader_check 超时 9→34"),
    Knob("task_contract", "bool", "auto", False, note="开工前拆解需求与模糊点、第一轮只读；四批合并无可复现效果（D-050）"),
    Knob("contract_version", "int", "auto", 1, values=(1, 2), requires=("task_contract",)),
    Knob("contract_conditional", "bool", "auto", False, requires=("task_contract",), note="H17：只在题面被评为模糊时启用契约"),
    Knob("gate_timeout_sec", "float", "auto", 180.0, lo=60.0, hi=240.0, requires=("contract_conditional",)),
    # ---- 人批准过的新机制（原为 review 档）----
    Knob("append_nudge", "bool", "auto", False, note="闭环第 1 轮发现：同一个文件连续 3 轮被 echo/printf >> 逐行追加时提醒整块写；"
         "2026-10-13 用户批准进入第 1 轮评测（\"先跑吧\"）"),
    # ---- text：闭环写文字，人批准文字（D-089）----
    Knob("custom_notes", "notes", "text", [], note="提醒：[{trigger, text}]，trigger 从固定菜单选（见 note_triggers），"
         "text ≤60 词、只能用 {n} / {files} 两个占位符；最多 2 条；触发时附在终端输出末尾，每条每个 trial 最多 3 次"),
    Knob("skills", "skills", "text", [], note="只含文字的 skill：[{name, description, body}]，name 小写字母数字和连字符，"
         "description ≤30 词，body ≤300 词；最多 2 个；题面后面列出名字和简介，模型需要时自己打开全文"),
    # ---- review：新机制，人批准之后才改成 auto ----
    # ---- frozen ----
    Knob("raw_log", "bool", "frozen", True, note="观察阶段要读原始回复：闭环生成的配置一律开（agent.py 里默认关）"),
    Knob("teacher_hint", "bool", "frozen", False, note="Teacher 看参考解与隐藏测试：只能用于训练采样，部署用的 harness 绝不能开"),
    Knob("max_turns", "int", "frozen", 100, note="评测协议"),
    Knob("enable_summarize", "bool", "frozen", True, note="评测协议"),
    Knob("proactive_summarization_threshold", "int", "frozen", 8000, note="评测协议"),
]}

AUTO = tuple(k for k, v in KNOBS.items() if v.tier == "auto")
TEXT = tuple(k for k, v in KNOBS.items() if v.tier == "text")
POLICY = AUTO + TEXT                      # 进版本配置、指纹和 Harbor 配置的选项
MAX_NOTES, MAX_SKILLS = 2, 2
NOTE_MAX_WORDS, SKILL_DESC_MAX_WORDS, SKILL_BODY_MAX_WORDS = 60, 30, 300
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")
FROZEN = tuple(k for k, v in KNOBS.items() if v.tier == "frozen")
# 训练专用、只在采样配置里出现的选项：出现在候选里一律拒绝
TRAINING_ONLY = ("teacher_hint", "teacher_model", "teacher_api_key_env", "teacher_knowledge", "hint_every", "hint_max",
                 "hint_max_words", "teacher_max_calls", "teacher_timeout_sec", "store_all_messages")


def _normalize(knob: Knob, v: Any) -> Any:
    """数值统一类型（60 和 60.0 是同一个值），避免同一个 harness 算出两个指纹。"""
    if knob.kind == "float" and isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if knob.kind == "int" and isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer():
        return int(v)
    if knob.kind in ("notes", "skills") and isinstance(v, (list, tuple)):
        return [{k2: (x[k2].strip() if isinstance(x.get(k2), str) else x.get(k2)) for k2 in sorted(x)} for x in v if isinstance(x, dict)]
    return v


def policy_options(options: dict[str, Any]) -> dict[str, Any]:
    """只保留 auto 和 text 范围内的选项（缺的补默认值、数值统一类型），用于比较、指纹和记录。"""
    return {k: _normalize(KNOBS[k], options.get(k, KNOBS[k].default)) for k in POLICY}


def _active(k: str, pol: dict[str, Any], memo: dict[str, bool]) -> bool:
    """选项 k 起不起作用：它依赖的每个开关都必须打开，而且那个开关本身也起作用（逐层往上查）。"""
    if k not in memo:
        memo[k] = all(bool(pol.get(r)) and _active(r, pol, memo) for r in KNOBS[k].requires)
    return memo[k]


def effective_options(options: dict[str, Any]) -> dict[str, Any]:
    """去掉"依赖的开关没开、所以不起作用"的参数：两个配置只差一个不起作用的参数时，它们其实是同一个 harness。"""
    pol, memo = policy_options(options), {}
    return {k: v for k, v in pol.items() if _active(k, pol, memo)}


def _requirement_met(opts: dict[str, Any], req: str) -> bool:
    return bool(opts.get(req))


def fingerprint(options: dict[str, Any]) -> str:
    """有效配置的指纹：同一个 harness（只差不起作用的参数）指纹相同。取默认值的选项不进指纹，
    这样以后新加一个开关（默认关）不会改变已有版本的指纹。"""
    eff = effective_options(options)
    blob = json.dumps({k: v for k, v in eff.items() if v != KNOBS[k].default}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


@dataclass
class Validation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)      # 应用改动后的完整 auto 选项
    effective_changes: dict[str, Any] = field(default_factory=dict)


def validate_change(base: dict[str, Any], changes: dict[str, Any]) -> Validation:
    """检查一个候选改动是否落在 auto 范围内，并返回应用后的配置。

    拒绝：frozen / 训练专用 / 未知选项、类型或取值越界、依赖关系不满足、改完和原来是同一个 harness。
    """
    errors: list[str] = []
    if not isinstance(changes, dict) or not changes:
        return Validation(False, ["empty change"])
    new = policy_options(base)
    for k, v in changes.items():
        if k in TRAINING_ONLY or (k in KNOBS and KNOBS[k].tier == "frozen"):
            errors.append(f"{k}: frozen / training-only, cannot be changed by the loop")
            continue
        if k in KNOBS and KNOBS[k].tier == "review":
            errors.append(f"{k}: review-tier mechanism, needs human approval before the loop may use it")
            continue
        if k not in KNOBS:
            errors.append(f"{k}: unknown option (new mechanisms go to review proposals, not auto changes)")
            continue
        knob = KNOBS[k]
        ok, val, why = _coerce(knob, v)
        if not ok:
            errors.append(f"{k}: {why}")
            continue
        new[k] = val
    for k, knob in KNOBS.items():
        if knob.tier not in ("auto", "text") or k not in changes:
            continue
        for r in knob.requires:
            if not _requirement_met(new, r):
                errors.append(f"{k}: requires {r}=true in the same configuration")
    if new.get("contract_conditional") and new.get("contract_version", 1) != 1:
        errors.append("contract_conditional only works with contract_version=1 (H17)")
    before, after = effective_options(base), effective_options(new)
    eff = {k: after.get(k) for k in set(before) | set(after) if before.get(k) != after.get(k)}
    if not errors and not eff:
        errors.append("no effective change: the resulting harness is identical to the base")
    return Validation(not errors, errors, new, eff)


def _coerce(knob: Knob, v: Any) -> tuple[bool, Any, str]:
    if knob.kind == "bool":
        if isinstance(v, bool):
            return True, v, ""
        return False, None, f"expected true/false, got {v!r}"
    if knob.kind == "enum":
        if v in knob.values:
            return True, v, ""
        return False, None, f"expected one of {list(knob.values)}, got {v!r}"
    if knob.kind in ("int", "float"):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False, None, f"expected a number, got {v!r}"
        if knob.values and v not in knob.values:
            return False, None, f"expected one of {list(knob.values)}, got {v!r}"
        if not math.isfinite(v):
            return False, None, f"not a finite number: {v!r}"
        if knob.lo is not None and v < knob.lo or knob.hi is not None and v > knob.hi:
            return False, None, f"out of range [{knob.lo}, {knob.hi}]: {v!r}"
        return True, (int(v) if knob.kind == "int" else float(v)), ""
    if knob.kind == "notes":
        return _coerce_notes(v)
    if knob.kind == "skills":
        return _coerce_skills(v)
    return False, None, f"unsupported kind {knob.kind}"


def _words(t: str) -> int:
    return len(re.findall(r"\S+", t))


def _coerce_notes(v: Any) -> tuple[bool, Any, str]:
    """提醒只查格式；文字内容（泄题、催交卷）由 notes.screen_note 查，人再批准。"""
    if not isinstance(v, list) or not v or len(v) > MAX_NOTES:
        return False, None, f"expected a list of 1–{MAX_NOTES} notes"
    out = []
    for x in v:
        if not isinstance(x, dict) or set(x) != {"trigger", "text"}:
            return False, None, "each note must be exactly {trigger, text}"
        if x["trigger"] not in NOTE_TRIGGERS:
            return False, None, f"unknown trigger {x['trigger']!r}; choose from {sorted(NOTE_TRIGGERS)}"
        t = x["text"]
        if not isinstance(t, str) or not t.strip() or _words(t) > NOTE_MAX_WORDS:
            return False, None, f"note text must be 1–{NOTE_MAX_WORDS} words"
        bad = set(re.findall(r"\{([^{}]*)\}", t)) - set(NOTE_PLACEHOLDERS)
        if bad:
            return False, None, f"note text may only use the placeholders {{n}} and {{files}}, found {sorted(bad)}"
        if "{files}" in t and x["trigger"] != "append_streak":
            return False, None, "{files} is only filled in for the append_streak trigger"
        out.append({"text": t.strip(), "trigger": x["trigger"]})
    if len({x["trigger"] for x in out}) < len(out):
        return False, None, "two notes on the same trigger"
    return True, out, ""


def _coerce_skills(v: Any) -> tuple[bool, Any, str]:
    if not isinstance(v, list) or not v or len(v) > MAX_SKILLS:
        return False, None, f"expected a list of 1–{MAX_SKILLS} skills"
    out = []
    for x in v:
        if not isinstance(x, dict) or set(x) != {"name", "description", "body"}:
            return False, None, "each skill must be exactly {name, description, body}"
        if not isinstance(x["name"], str) or not _SKILL_NAME_RE.match(x["name"]):
            return False, None, f"skill name must be 3–40 lowercase letters, digits or hyphens: {x['name']!r}"
        if not isinstance(x["description"], str) or not x["description"].strip() or _words(x["description"]) > SKILL_DESC_MAX_WORDS:
            return False, None, f"skill description must be 1–{SKILL_DESC_MAX_WORDS} words"
        if not isinstance(x["body"], str) or not x["body"].strip() or _words(x["body"]) > SKILL_BODY_MAX_WORDS:
            return False, None, f"skill body must be 1–{SKILL_BODY_MAX_WORDS} words"
        out.append({"body": x["body"].strip(), "description": x["description"].strip(), "name": x["name"]})
    if len({x["name"] for x in out}) < len(out):
        return False, None, "two skills with the same name"
    return True, out, ""


def scope_table() -> list[dict[str, Any]]:
    """给提议模型看的范围表。"""
    rows = []
    for k, knob in KNOBS.items():
        rng = (list(knob.values) if knob.values else [knob.lo, knob.hi] if knob.lo is not None else None)
        if knob.kind == "notes":
            rng = {"triggers": NOTE_TRIGGERS, "placeholders": [f"{{{p}}}" for p in NOTE_PLACEHOLDERS], "max_notes": MAX_NOTES,
                   "max_words": NOTE_MAX_WORDS}
        elif knob.kind == "skills":
            rng = {"max_skills": MAX_SKILLS, "description_max_words": SKILL_DESC_MAX_WORDS, "body_max_words": SKILL_BODY_MAX_WORDS}
        rows.append({"option": k, "tier": knob.tier, "type": knob.kind, "default": knob.default, "allowed": rng,
                     "requires": list(knob.requires), "note": knob.note})
    return rows
