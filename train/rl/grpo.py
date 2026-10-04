"""PSP 式 GRPO（D-072）的纯函数：组内 advantage、难题提示的开关、选题、把一个 trial 变成训练样本。本地可单测。

一步的流程（grpo_loop.py 串起来）：
  选 16 道训练题 ──▶ 当前策略每题做 8 次（H2）──▶ 判分 0/1 ──▶ 组内 advantage ──▶ 一次 LoRA 更新（grpo_step.py）──▶ 挂新适配器
难题提示（PSP：提示留在上下文、不进 loss）：某题最近一组“不带提示”全挂 → 下次带规则（gpt-6-sol 读这组失败写的，psp_rules.py）；
带规则的一组过了一半以上、或这一步额外的“不带提示试做”做对过（D-075）→ 下次去掉规则；带规则仍全挂 → 用这组失败重写规则。
"""
from __future__ import annotations

import math

from terminus2_patches.teacher import MARK

PLAIN, HINTED = "plain", "hinted"
VALID_FAILURES = ("AgentTimeoutError", "VerifierTimeoutError")   # 超时算做错（奖励 0），其余异常算基础设施故障，不进组


def group_advantages(rewards: list[float], eps: float = 1e-6) -> list[float] | None:
    """GRPO：(r − 组均值) / 组标准差。全对或全错（标准差 0）没有信号 → None；少于 2 个有效 trial → None。"""
    if len(rewards) < 2:
        return None
    mu = sum(rewards) / len(rewards)
    sd = math.sqrt(sum((r - mu) ** 2 for r in rewards) / len(rewards))
    if sd < eps:
        return None
    return [(r - mu) / sd for r in rewards]


def next_mode(mode: str, passes: int, n: int, probe_passes: int = 0) -> tuple[str, bool]:
    """(下次的模式, 要不要用这组的失败重写规则)。
    probe_passes：这一步给带提示的题额外做的几次“不带提示的试做”里做对的次数（D-075，照 PSP / Guide / ADHint 每次都检验不带提示行不行）；
    试做做对过 → 下次就不带提示。"""
    if mode == PLAIN:
        return (HINTED, True) if passes == 0 else (PLAIN, False)
    if probe_passes > 0:
        return PLAIN, False
    if passes == 0:
        return HINTED, True
    return (PLAIN, False) if passes * 2 >= n else (HINTED, False)


def pick_tasks(order: list[str], cursor: int, k: int) -> tuple[list[str], int]:
    """按固定的打乱顺序循环取 k 道（每道训练题被轮到的次数相同）。"""
    out = [order[(cursor + i) % len(order)] for i in range(k)]
    return out, (cursor + k) % len(order)


def trial_reward(result: dict) -> float | None:
    """判分 0/1；基础设施故障 → None（不进组）。"""
    exc = (result.get("exception_info") or {}).get("exception_type")
    if exc and exc not in VALID_FAILURES:
        return None
    rew = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    return 1.0 if (rew or 0) >= 1 else 0.0


def without_hints(msgs: list[dict], rules_block: str | None, teacher_hints: list[dict]) -> list[dict] | None:
    """同一段对话去掉提示后的样子（算“提示依赖度”用，HiLL 2604.00698）：去掉第一条 user 消息里的规则块，或各条 user 消息里的 Reviewer note。
    训练标记（train=False）原样保留，所以两边算 loss 的是同一批 Qwen 自己的 token。找不到要删的原文 → None。"""
    out = [dict(m) for m in msgs]
    if rules_block:
        first = next((m for m in out if m["role"] == "user"), None)
        if first is None or rules_block not in first["content"]:
            return None
        first["content"] = first["content"].replace(rules_block, "", 1)
        return out
    notes = [MARK + h["text"] for h in teacher_hints]
    if not notes:
        return None
    for note in notes:
        hit = next((m for m in out if m["role"] == "user" and note in m["content"]), None)
        if hit is None:
            return None
        for sep in ("\n\n", "\n", ""):
            if sep + note in hit["content"]:
                hit["content"] = hit["content"].replace(sep + note, "", 1)
                break
    return out


def trial_example(result: dict, advantage: float, rules_block: str | None = None) -> tuple[dict | None, str]:
    """一个 trial → 训练样本 {messages, advantage}。messages 是发给模型的完整对话（逐字），只有 Qwen 自己的回复算 loss。
    advantage > 0 时，被交卷把关（H2）或 Teacher 在宣布完成时打回的那句“我做完了”标 train=False：它是错的交卷，不该因为后来做对而被奖励；
    advantage < 0 时照常算（错的交卷正该被罚）。摘要过的对话不连续 → 不进梯度（奖励仍参与组内基线）。"""
    md = (result.get("agent_result") or {}).get("metadata") or {}
    msgs = md.get("all_messages")
    if not msgs:
        return None, "no_all_messages"
    if md.get("summarization_count"):
        return None, "summarized"
    msgs = [{"role": m["role"], "content": m["content"]} for m in msgs]
    patched = md.get("patched") or {}
    if advantage > 0:
        turns = [g["turn"] for g in patched.get("completion_gate") or []]
        turns += [h["turn"] for h in (patched.get("teacher") or {}).get("hints") or [] if h.get("at_claim")]
        for t in turns:
            i = 2 * t - 1                      # all_messages：[user(开场), assistant(第 1 轮), user(观察), ...] → 第 t 轮回复在 2t−1
            if i >= len(msgs) or msgs[i]["role"] != "assistant":
                return None, "claim_turn_misaligned"
            msgs[i]["train"] = False
    if not any(m["role"] == "assistant" and m.get("train") is not False for m in msgs):
        return None, "no_trainable_turn"
    ex = {"messages": msgs, "advantage": advantage, "task": result["task_name"].split("/")[-1]}
    if advantage > 0:     # 带提示且做对的轨迹：另存一份去掉提示的，Pod 上顺便算提示依赖度（只记录，不参与训练）
        t_hints = (patched.get("teacher") or {}).get("hints") or []
        nohint = without_hints(msgs, rules_block, t_hints) if (rules_block or t_hints) else None
        if nohint is not None:
            ex["messages_nohint"] = nohint
    return ex, "ok"
