"""规则层：纯函数，输入 TrialRecord，输出 FailureLabel 列表。

优先级（借 rollout-mvp runner.attribute 与 taskengine classify）：
  ENVIRONMENT 先判、命中即停止叠加 → TASK → 预算/过早完成 → 其余按证据叠加。
通过的 trial 不产生失败标签（但会产生计数型 NUMERIC 标签，用于统计）。
"""
from __future__ import annotations

import re

from agenteval.attribute.signals import (COMMAND_ERROR_RE, HARD_RUNTIME_RE, INTEGRITY_RE, INTERACTIVE_PROMPT_RE, READ_CMD_RE,
                                         THRESHOLDS, WRITE_CMD_RE)
from agenteval.schemas import FailureLabel, Step, TrialRecord


def _lab(name, value, dtype, tb, blame, conf, comment, onset=None, kind="failure") -> FailureLabel:
    return FailureLabel(name=name, value=value, data_type=dtype, source="RULE", tb_class=tb,
                        blame_candidate=blame, confidence=conf, comment=comment, onset_step=onset, kind=kind)


def _obs_head(s: Step, n: int = 160) -> str:
    return s.observation_text.strip().replace("\n", " ")[:n]


def _sig(s: Step) -> tuple[str, ...]:
    return tuple(k.strip() for k in s.keystrokes)


def _is_empty_wait(s: Step) -> bool:
    return bool(s.keystrokes) and all(not k.strip() for k in s.keystrokes)


def _runs(items: list, key) -> list[tuple[int, int, object]]:
    """连续相同 key 的游程：(start_idx, length, key)。"""
    out, i = [], 0
    while i < len(items):
        k, j = key(items[i]), i + 1
        while j < len(items) and key(items[j]) == k:
            j += 1
        out.append((i, j - i, k)); i = j
    return out


def environment_labels(t: TrialRecord) -> list[FailureLabel]:
    labs = []
    if t.status == "setup_failed":
        labs.append(_lab("SETUP_FAILED", True, "BOOLEAN", "ENVIRONMENT", "ENVIRONMENT", 0.95,
                         f"exception before agent_execution: {t.exception_type}: {t.exception_message}"))
    elif t.status == "agent_error":
        msg = (t.exception_message or "")
        if re.search(r"flagged|content policy|content_filter|safety|refus", msg, re.I):
            labs.append(_lab("PROVIDER_REFUSAL", True, "BOOLEAN", "ENVIRONMENT", "ENVIRONMENT", 0.95,
                             f"model provider refused the request: {msg[:200]}"))
        else:
            labs.append(_lab("AGENT_RUNTIME_ERROR", True, "BOOLEAN", "ENVIRONMENT", "ENVIRONMENT", 0.9,
                             f"{t.exception_type}: {msg}"))
    elif t.status == "verifier_error":
        labs.append(_lab("VERIFIER_FAILURE", True, "BOOLEAN", "ENVIRONMENT", "ENVIRONMENT", 0.9,
                         f"no reward; exception={t.exception_type}"))
    # 轨迹里出现运行时硬信号（连接错误、限流）也算环境
    for s in t.agent_steps:
        m = HARD_RUNTIME_RE.search(s.observation_text)
        if m:
            labs.append(_lab("AGENT_RUNTIME_ERROR", True, "BOOLEAN", "ENVIRONMENT", "ENVIRONMENT", 0.7,
                             f"step {s.step_id}: {m.group(0)}", s.step_id))
            break
    return labs


def counting_labels(t: TrialRecord) -> list[FailureLabel]:
    """通过与失败都产生的计数型标签（NUMERIC）。"""
    steps = t.agent_steps
    labs = []
    polling = sum(1 for s in steps if _is_empty_wait(s))
    parse_errs = sum(1 for s in steps if s.parse_error)
    cmd_errs = sum(len(COMMAND_ERROR_RE.findall(s.observation_text)) for s in steps)
    truncated = sum(1 for s in steps if s.truncated)
    compactions = t.summarization_count or sum(1 for s in t.steps if s.compaction_boundary)
    C = dict(kind="count")
    labs += [
        _lab("polling_turns", polling, "NUMERIC", "NONE", "UNKNOWN", 1.0, "keystrokes 为空的轮数", **C),
        _lab("parse_error_turns", parse_errs, "NUMERIC", "NONE", "UNKNOWN", 1.0, "观察以 'Previous response had parsing errors' 开头的轮数", **C),
        _lab("command_error_hits", cmd_errs, "NUMERIC", "NONE", "UNKNOWN", 1.0, "command not found / No such file / Permission denied 命中次数", **C),
        _lab("truncated_observations", truncated, "NUMERIC", "NONE", "UNKNOWN", 1.0, "含截断标记的观察数", **C),
        _lab("compactions", compactions, "NUMERIC", "NONE", "UNKNOWN", 1.0, "上下文压缩次数", **C),
        _lab("claimed_complete", any(s.claimed_complete for s in steps), "BOOLEAN", "NONE", "UNKNOWN", 1.0, "是否出现 mark_task_complete", **C),
    ]
    return labs


def integrity_labels(t: TrialRecord) -> list[FailureLabel]:
    """通过与失败都检查：碰判题文件 / harness 日志 / 全盘扫描 → INTEGRITY_SUSPECT（DSec §6.4；Harbor analyze 的 reward_hacking）。"""
    for s in t.agent_steps:
        for k in s.keystrokes:
            m = INTEGRITY_RE.search(k)
            if m:
                return [_lab("INTEGRITY_SUSPECT", True, "BOOLEAN", "Verification", "MODEL", 0.6,
                             f"step {s.step_id} touched {m.group(0)!r}: {k.strip()[:120]!r}", s.step_id)]
    return []


def failure_labels(t: TrialRecord) -> list[FailureLabel]:
    """失败 trial 的规则标签。"""
    if t.passed:
        return []
    env = environment_labels(t)
    if env:
        return env  # 环境原因能解释就不再叠加（taskengine）
    steps = t.agent_steps
    labs: list[FailureLabel] = []
    th = THRESHOLDS

    # FORMAT：解析错误占比过半（rollout-mvp）
    if steps:
        share = sum(1 for s in steps if s.parse_error) / len(steps)
        if share > th["format_parse_error_share"]:
            first = next(s for s in steps if s.parse_error)
            labs.append(_lab("FORMAT", True, "BOOLEAN", "Execution", "MIXED", 0.9,
                             f"{share:.0%} of turns were parse errors; first at step {first.step_id}", first.step_id))
            return labs

    # 预算 / 过早完成
    claimed = [s for s in steps if s.claimed_complete]
    if claimed:
        labs.append(_lab("PREMATURE_COMPLETION", True, "BOOLEAN", "Verification", "MIXED", 0.95,
                         f"mark_task_complete at step {claimed[0].step_id} but reward={t.reward}", claimed[0].step_id))
    elif t.status == "agent_timeout" or (t.metadata.get("max_turns") and t.n_episodes >= t.metadata["max_turns"]):
        labs.append(_lab("BUDGET_EXHAUSTED", True, "BOOLEAN", "Execution", "MIXED", 0.9,
                         f"status={t.status}, n_episodes={t.n_episodes}", steps[-1].step_id if steps else None))

    # POLLING：连续空等待
    for start, length, _ in _runs(steps, _is_empty_wait):
        if _ and length >= th["polling_min_consecutive"]:
            labs.append(_lab("POLLING", True, "BOOLEAN", "Execution", "HARNESS", 0.85,
                             f"{length} consecutive empty-keystroke turns from step {steps[start].step_id}", steps[start].step_id))
            break

    # LOOP 三变体（OpenHands StuckDetector）
    non_empty = [s for s in steps if s.keystrokes and not _is_empty_wait(s)]
    for start, length, sig in _runs(non_empty, _sig):
        run = non_empty[start:start + length]
        if length >= th["loop_same_error_min"] and all(COMMAND_ERROR_RE.search(x.observation_text) or re.search(r"\b[Ee]rror\b", x.observation_text) for x in run):
            labs.append(_lab("LOOP", "same_action_same_error", "CATEGORICAL", "Execution", "MIXED", 0.8,
                             f"{length}x identical failing keystrokes from step {run[0].step_id}: {sig[0][:60]!r}", run[0].step_id))
            break
        if length >= th["loop_same_obs_min"] and len({_obs_head(x) for x in run}) == 1:
            labs.append(_lab("LOOP", "same_action_same_observation", "CATEGORICAL", "Execution", "MIXED", 0.85,
                             f"{length}x identical keystrokes+observation from step {run[0].step_id}: {sig[0][:60]!r}", run[0].step_id))
            break
    if not any(l.name == "LOOP" for l in labs) and len(non_empty) >= 2 * th["loop_alternating_min_cycles"]:
        sigs = [_sig(s) for s in non_empty]
        for i in range(len(sigs) - 2 * th["loop_alternating_min_cycles"] + 1):
            a, b = sigs[i], sigs[i + 1]
            if a != b and all(sigs[i + k] == (a if k % 2 == 0 else b) for k in range(2 * th["loop_alternating_min_cycles"])):
                labs.append(_lab("LOOP", "alternating", "CATEGORICAL", "Execution", "MIXED", 0.8,
                                 f"A/B alternation for {th['loop_alternating_min_cycles']} cycles from step {non_empty[i].step_id}", non_empty[i].step_id))
                break

    # STUCK_AT_PROMPT：观察末尾是交互提示，且下一轮没有应答（下一轮为空等待或重复同一命令）
    for i, s in enumerate(steps[:-1]):
        tail = s.observation_text.rstrip()[-200:]
        if INTERACTIVE_PROMPT_RE.search(tail):
            nxt = steps[i + 1]
            if _is_empty_wait(nxt) or _sig(nxt) == _sig(s):
                labs.append(_lab("STUCK_AT_PROMPT", True, "BOOLEAN", "Execution", "HARNESS", 0.75,
                                 f"interactive prompt at step {s.step_id}: {tail[-80:]!r}; next turn did not answer it", s.step_id))
                break

    # TRUNCATED_READ：读类命令的输出被截断，且随后两轮内有写操作
    for i, s in enumerate(steps):
        if s.truncated and any(READ_CMD_RE.match(k) for k in s.keystrokes):
            follow = steps[i + 1:i + 3]
            wrote = any(WRITE_CMD_RE.search(k) for f in follow for k in f.keystrokes)
            labs.append(_lab("TRUNCATED_READ", True, "BOOLEAN", "Execution", "HARNESS", 0.8 if wrote else 0.5,
                             f"truncated read at step {s.step_id}" + (" followed by a write within 2 turns" if wrote else ""), s.step_id))
            break

    # COMPACTION：候选信号，交给判官判 GOAL_DRIFT；COMPACTION_LOOP 由规则判
    comp_idx = [i for i, s in enumerate(t.steps) if s.compaction_boundary]
    if t.summarization_count or comp_idx:
        labs.append(_lab("COMPACTION_OCCURRED", True, "BOOLEAN", "Coherence", "UNKNOWN", 1.0,
                         f"summarization_count={t.summarization_count}", (t.steps[comp_idx[0]].step_id if comp_idx else None)))
        if len(comp_idx) >= 2:
            for a, b in zip(comp_idx, comp_idx[1:]):
                between = {tuple(s.keystrokes) for s in t.steps[a:b] if s.source == "agent" and s.keystrokes}
                if len(between) <= 1:
                    labs.append(_lab("COMPACTION_LOOP", True, "BOOLEAN", "Coherence", "HARNESS", 0.8,
                                     f"compactions at steps {t.steps[a].step_id} and {t.steps[b].step_id} with no new distinct commands between", t.steps[a].step_id))
                    break

    # 命令错误计数达到阈值 → 记为信号（不单独定失败）
    cmd_errs = sum(len(COMMAND_ERROR_RE.findall(s.observation_text)) for s in steps)
    if cmd_errs >= th["command_error_min"]:
        first = next((s for s in steps if COMMAND_ERROR_RE.search(s.observation_text)), None)
        labs.append(_lab("COMMAND_NOT_FOUND", cmd_errs, "NUMERIC", "Execution", "MODEL", 0.6,
                         f"{cmd_errs} command-error hits", first.step_id if first else None))

    if not labs:
        labs.append(_lab("CAPABILITY", True, "BOOLEAN", "NONE", "MODEL", 0.5,
                         "no rule fired; judge decides (SPEC_MISINTERPRETATION / INSUFFICIENT_VERIFICATION / ...)"))
    return labs


def label_trial(t: TrialRecord, max_turns: int | None = None) -> TrialRecord:
    if max_turns:
        t.metadata["max_turns"] = max_turns
    t.labels = counting_labels(t) + integrity_labels(t) + failure_labels(t)
    return t
