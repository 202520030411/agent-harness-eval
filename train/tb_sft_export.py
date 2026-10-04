"""Harbor + Terminus2Patched 的 rollout → SFT 样本（QWEN_PLAN §4；不蒸馏：每个 assistant token 都是 Qwen 自己当时生成的）。

样本来源：result.json 的 agent_result.metadata.all_messages——发给模型的完整对话，逐字（rollout 配置要开 `store_all_messages: true`）。
一个 trial 要全部满足才进训练集：
  1 验证器通过（reward ≥ 1），没有基础设施报错
  2 没发生上下文摘要（summarization_count == 0；摘要会改写历史，样本就不是连续对话了）
  3 每轮格式都合法：raw_responses.jsonl 里没有解析报错，也没有靠宽松解析才修好的轮（默认；--allow-fixed 放开）
  4 没被交卷把关打回过（metadata.patched.completion_gate 为空；--keep-gated 放开）
  4b 第一次宣布完成时，最后一次改文件之后真的运行过东西（与 H2 把关同一个函数 no_run_after_last_write）
  4c 宣布完成那一轮的 analysis / plan 里没有承认没做成的措辞（同一个 admission_quote）
  5 rubric 分 ≥ 阈值（给了 --rubric-scores 时；文件每行 {"trial": ..., "score": ...}）
  6 给了提示的题：把提示原文从第一条 user 消息里删掉；assistant 的文字与提示有任何 8 词连续重合就整条丢弃（模型在复述提示）
  7 实时 Teacher 提示（D-069，metadata.patched.teacher.hints）：例行提示从那一轮的观察里逐字删掉；在“宣布完成”那一轮给的提示，
    连同那句宣布完成的回复一起删掉（那一轮若执行过命令则整条丢弃，删了会前后不接）；第 4b/4c 条的检查跳过被删掉的那次宣布完成
    --keep-teacher-hints（D-071 方案 B）：提示留在对话里（user 角色，不算 loss），模型接提示的话也保留；被打断的那句“宣布完成”
    标 train=False（不学这个错误的交卷），复述 / 提到提示不再丢弃
用法（服务器）：python train/tb_sft_export.py --jobs /root/work/jobs/roll-a /root/work/jobs/roll-b --hints hints.json --out sft.jsonl
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminus2_patches.helpers import admission_quote, no_run_after_last_write  # noqa: E402
from terminus2_patches.teacher import MARK  # noqa: E402

_WORD = re.compile(r"\w+")


def ngrams(text: str, n: int = 8) -> set[tuple[str, ...]]:
    w = [x.lower() for x in _WORD.findall(text or "")]
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def strip_teacher_hints(msgs: list[dict], hints: list[dict]) -> tuple[list[dict] | None, str | None]:
    """删掉实时 Teacher 提示（D-069）。all_messages 的排列：[user(开场), assistant(第 1 轮), user(第 1 轮后的观察), ...]，
    所以第 k 轮的回复在下标 2k-1，紧跟的观察在 2k。"""
    msgs = [dict(m) for m in msgs]
    drop = set()
    for h in hints:
        s = MARK + h["text"]
        if h.get("at_claim"):
            if h.get("claim_had_commands"):
                return None, "claim_hint_after_commands"
            ai, ui = 2 * h["turn"] - 1, 2 * h["turn"]
            if ui >= len(msgs) or msgs[ai]["role"] != "assistant" or msgs[ui]["role"] != "user" or s not in msgs[ui]["content"]:
                return None, "claim_hint_misaligned"
            drop.update({ai, ui})
            continue
        for m in msgs:
            if m["role"] == "user" and s in m["content"]:
                for sep in ("\n\n", "\n", ""):
                    if sep + s in m["content"]:
                        m["content"] = m["content"].replace(sep + s, "", 1)
                        break
                break
        else:
            return None, "teacher_hint_not_found"
    return [m for i, m in enumerate(msgs) if i not in drop], None


def claim_behavior(d: Path, skip_turns: set[int] | None = None) -> dict | None:
    """第一次宣布完成那一刻：之前执行过的命令、那一轮的文字。没宣布过完成就 None。
    skip_turns：被 Teacher 在宣布完成时打断、训练前会删掉的那几轮（不算“第一次宣布完成”）。"""
    skip_turns = skip_turns or set()
    try:
        t = json.load(open(d / "agent" / "trajectory.json"))
    except Exception:  # noqa: BLE001
        return None
    executed = []
    k = 0
    for s in t.get("steps", []):
        if s.get("source") != "agent":
            continue
        k += 1
        calls = s.get("tool_calls") or []
        executed += [(c.get("arguments") or {}).get("keystrokes", "") for c in calls if c.get("function_name") == "bash_command"]
        if k not in skip_turns and any(c.get("function_name") == "mark_task_complete" for c in calls):
            return {"no_run_after_last_write": no_run_after_last_write(executed), "admission": admission_quote(s.get("message") or "")}
    return None


def check_trial(d: Path, hints: dict[str, str], rubric: dict[str, float] | None, min_rubric: float,
                allow_fixed: bool, keep_gated: bool, keep_teacher_hints: bool = False) -> tuple[dict | None, str]:
    """返回 (样本, 原因)。样本为 None 时，原因说明为什么丢。"""
    try:
        r = json.load(open(d / "result.json"))
    except Exception:  # noqa: BLE001
        return None, "no_result"
    if r.get("exception_info"):
        return None, "infra_error"
    rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    if rew is None or rew < 1:
        return None, "not_passed"
    md = (r.get("agent_result") or {}).get("metadata") or {}
    msgs = md.get("all_messages")
    if not msgs:
        return None, "no_all_messages"
    if md.get("summarization_count"):
        return None, "summarized"
    patched = md.get("patched") or {}
    if patched.get("completion_gate") and not keep_gated:
        return None, "gated"
    t_hints = (patched.get("teacher") or {}).get("hints") or []
    behav = claim_behavior(d, {h["turn"] for h in t_hints if h.get("at_claim")})
    if behav is None:
        return None, "no_claim"
    if behav["no_run_after_last_write"]:
        return None, "unverified_claim"
    if behav["admission"]:
        return None, "admits_failure"
    raw_path = d / "agent" / "raw_responses.jsonl"
    if raw_path.exists():
        for line in open(raw_path):
            row = json.loads(line)
            if row.get("parse_error"):
                return None, "parse_error"
            if row.get("fix") and not allow_fixed:
                return None, "lenient_fixed"
    elif not allow_fixed:
        return None, "no_raw_log"
    task = r["task_name"].split("/")[-1]
    if rubric is not None:
        s = rubric.get(d.name)
        if s is None or s < min_rubric:
            return None, "rubric"
    msgs = [dict(m) for m in msgs]
    if t_hints and keep_teacher_hints:
        for h in t_hints:
            if h.get("at_claim"):
                ai = 2 * h["turn"] - 1
                if ai >= len(msgs) or msgs[ai]["role"] != "assistant":
                    return None, "claim_hint_misaligned"
                msgs[ai]["train"] = False     # 被 Teacher 打断的错误交卷：留在上下文里，但不学
        t_hints_for_filters = []
    else:
        t_hints_for_filters = t_hints
    if t_hints_for_filters:
        msgs, why = strip_teacher_hints(msgs, t_hints)
        if why:
            return None, why
        tg = set().union(*(ngrams(h["text"]) for h in t_hints))
        if any(tg & ngrams(m["content"]) for m in msgs if m["role"] == "assistant"):
            return None, "echoes_teacher_hint"
        if any(re.search(r"\b(hint|reviewer)", m["content"], re.I) for m in msgs if m["role"] == "assistant"):
            return None, "mentions_teacher_hint"
    hint = hints.get(task)
    if hint:
        first = next((m for m in msgs if m["role"] == "user"), None)
        if first is None or hint not in first["content"]:
            return None, "hint_not_found"
        first["content"] = first["content"].replace(hint, "")
        hg = ngrams(hint)
        if any(hg & ngrams(m["content"]) for m in msgs if m["role"] == "assistant"):
            return None, "echoes_hint"
        if any(re.search(r"\bhint", m["content"], re.I) for m in msgs if m["role"] == "assistant"):
            return None, "mentions_hint"   # “按提示所说……”：删掉提示后这句话就没有来由
    if not any(m["role"] == "assistant" for m in msgs):
        return None, "no_assistant"
    return {"messages": [{"role": m["role"], "content": m["content"], **({"train": False} if m.get("train") is False else {})} for m in msgs],
            "trial": d.name, "task": task, "hinted": "teacher" if t_hints else bool(hint)}, "ok"


def main(a) -> None:
    hints = json.load(open(a.hints)) if a.hints else {}
    rubric = None
    if a.rubric_scores:
        rubric = {x["trial"]: float(x["score"]) for x in map(json.loads, open(a.rubric_scores)) if x.get("score") is not None}
    why = collections.Counter()
    kept = []
    for job in a.jobs:
        for d in sorted(Path(job).glob("*__*/")):
            ex, reason = check_trial(d, hints, rubric, a.min_rubric, a.allow_fixed, a.keep_gated, a.keep_teacher_hints)
            why[reason] += 1
            if ex:
                kept.append(ex)
    with open(a.out, "w") as f:
        for ex in kept:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    per_task = collections.Counter(ex["task"] for ex in kept)
    print(f"kept {len(kept)} trajectories from {sum(why.values())} trials over {len(per_task)} tasks -> {a.out}")
    print("reasons:", dict(why))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hints", help="JSON {task: 追加到题面里的提示原文}")
    ap.add_argument("--rubric-scores", help="jsonl，每行 {trial, score}")
    ap.add_argument("--min-rubric", type=float, default=0.8)
    ap.add_argument("--allow-fixed", action="store_true", help="保留靠宽松解析修好过的轮（默认丢：训练目标是标准 JSON）")
    ap.add_argument("--keep-gated", action="store_true", help="保留被交卷把关打回过的轨迹（默认丢：部署时不一定有把关）")
    ap.add_argument("--keep-teacher-hints", action="store_true", help="D-071 方案 B：实时提示留在对话里（不算 loss），被打断的交卷不学")
    main(ap.parse_args())
