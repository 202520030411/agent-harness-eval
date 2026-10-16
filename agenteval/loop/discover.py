"""自动找毛病（D-089，闭环第 2 阶段）：两家模型各读一遍失败轨迹，给出"哪种行为导致失败"，一致才采信；都说是新毛病的再归类。

这里只放纯函数（挑样本、压缩轨迹、拼提示、解析、对照两家结果、归类提示）；调用模型在 tools/loop_cycle.py discover。

规矩（照 2026-10-12 和用户定的 A 方案）：
- 每道题先挑一个失败的 trial，凑够 n 条；"有时过、有时不过"的题附一条同题成功的轨迹作对照。
- 已知毛病清单里故意去掉 line_by_line_write：看它能不能自己找回来（找不回来说明这一步不可靠）。
- 判官可以看判分输出来归因，但写出来的只能是行为层面的描述；归类结果交给提议模型之前，还要过泄题检查（notes.py 里
  "和某道题连续 6 个词相同 / 只在少数题里出现的标识符"那两条）。
- 新毛病要先写成固定规则、抽 20 个例子人工核对准确率，才进 modes.MODES；这里只给出"怎么认"的建议。
"""
from __future__ import annotations

import json
import random
import re
from typing import Any

# 已知毛病的英文说明（给判官看；和 modes.MODES 的 id 对应）。line_by_line_write 故意不列（找回测试）
KNOWN_EN: dict[str, str] = {
    "format_error": "replies were not the JSON the harness expects (format errors)",
    "turn_cap": "ran out of turns (an outcome: use it only if no specific behavior explains where the turns went)",
    "timeout": "ran out of wall-clock time (an outcome: use it only if no specific behavior explains where the time went)",
    "polling": "spent many turns waiting with empty commands",
    "stuck_at_prompt": "got stuck at an interactive prompt (pager, y/N question, unfinished quote)",
    "loop": "repeated the same failing action again and again",
    "truncated_read": "relied on command output that was cut off",
    "command_not_found": "used commands that are not installed",
    "echo_theater": "printed 'done' messages with echo instead of really checking",
    "false_success": "declared success while its own analysis said it had not worked",
    "claim_without_run": "declared completion without running anything after its last change",
    "premature_completion": "declared completion although the work was wrong or incomplete (no better description fits)",
}
HELD_OUT_MODE = "line_by_line_write"          # 找回测试：判官看不到这个毛病的名字
_SNAKE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
REQUIRED = ("category", "behavior", "harness_fixable")


def pick_trials(rows: list[dict], n: int = 80, seed: int = 0) -> list[dict]:
    """每道题先挑一个失败的 trial（轮流挑，题目顺序随机但固定），挑够 n 条。基础设施故障不算。
    返回 [{"trial", "task", "contrast": 同题通过的 trial 名或 None}]。"""
    rng = random.Random(seed)
    by_task: dict[str, list[dict]] = {}
    passed: dict[str, list[str]] = {}
    for r in rows:
        if r.get("infra"):
            continue
        if r.get("passed"):
            passed.setdefault(r["task"], []).append(r["trial"])
        else:
            by_task.setdefault(r["task"], []).append(r)
    tasks = sorted(by_task)
    rng.shuffle(tasks)
    for t in tasks:
        by_task[t].sort(key=lambda r: r["trial"])
        rng.shuffle(by_task[t])
    out, depth = [], 0
    while len(out) < n and any(len(by_task[t]) > depth for t in tasks):
        for t in tasks:
            if len(out) >= n:
                break
            if len(by_task[t]) > depth:
                r = by_task[t][depth]
                ok = sorted(passed.get(t, []))
                out.append({"trial": r["trial"], "task": t, "contrast": ok[0] if ok else None})
        depth += 1
    return out


def condense(traj: dict, head: int = 6, tail: int = 20, max_chars: int = 40000) -> str:
    """把轨迹压成"每轮一行"：前 head 轮和后 tail 轮带思路、命令和输出尾巴；中间只留命令。"""
    steps = [s for s in traj.get("steps") or [] if s.get("source") == "agent"]
    n = len(steps)
    lines = []
    for i, s in enumerate(steps, 1):
        cmds = []
        for tc in s.get("tool_calls") or []:
            if tc.get("function_name") == "bash_command":
                cmds.append(str((tc.get("arguments") or {}).get("keystrokes", "")))
            elif tc.get("function_name"):
                cmds.append(f"<{tc['function_name']}>")
        cmd = " ⏎ ".join(c.strip() for c in cmds if c.strip()) or "(no command)"
        full = i <= head or i > n - tail
        if full:
            obs = ""
            for res in ((s.get("observation") or {}).get("results") or []):
                obs += str(res.get("content", ""))
            msg = re.sub(r"\s+", " ", str(s.get("message") or ""))[:240]
            lines.append(f"T{i} | think: {msg} | cmd: {cmd[:400]} | out: …{obs[-500:]!r}")
        else:
            lines.append(f"T{i} | cmd: {cmd[:160]}")
    text = "\n".join(lines)
    if len(text) > max_chars:                         # 太长：中间再砍掉一段
        keep = max_chars // 2
        text = text[:keep] + "\n…(middle turns omitted)…\n" + text[-keep:]
    return text


def failure_summary(test_stdout: str, max_chars: int = 1500) -> str:
    """判分输出里"哪些检查没过"的几行（FAILED / E 开头 / AssertionError），只给判官归因用。"""
    keep = [l for l in (test_stdout or "").splitlines() if l.startswith(("FAILED", "E ", "ERROR")) or "Error" in l]
    return "\n".join(keep)[:max_chars] or "(no failure lines captured)"


JUDGE_SYSTEM = ("You diagnose why a terminal coding agent (a fixed LLM inside a harness) failed a task. You read its trajectory and "
                "name the agent BEHAVIOR that caused the failure, in general terms that would apply to other tasks too.")

JUDGE_TEMPLATE = """KNOWN FAILURE MODES (id: description):
{known}

TASK GIVEN TO THE AGENT:
{instruction}

RESULT: failed. Checks that did not pass (for your diagnosis only):
{failures}
{contrast}
TRAJECTORY OF THE FAILED ATTEMPT (one line per turn; T = turn number):
{trajectory}

Pick the ONE behavior that, had it not happened, would most likely have let the agent pass. Use a known mode id if one fits;
use "new" only if none fits. Describe the behavior in general terms: no file names, no values, nothing specific to this task.

Return ONLY a JSON object:
{{"failure_turn": <turn number where it went wrong, or null>,
  "category": "<a known mode id, or new>",
  "new_category": "<short snake_case name, only when category is new>",
  "behavior": "<at most 25 words, general terms>",
  "harness_fixable": "<yes | no | unsure: could a change to the harness (reminders, checks, tools) plausibly prevent it?>",
  "why": "<at most 40 words>"}}"""


def judge_prompt(instruction: str, failures: str, trajectory: str, contrast: str | None = None) -> tuple[str, str]:
    known = "\n".join(f"- {k}: {v}" for k, v in KNOWN_EN.items())
    c = ("\nA SUCCESSFUL ATTEMPT AT THE SAME TASK, for contrast (condensed):\n" + contrast + "\n") if contrast else ""
    return JUDGE_SYSTEM, JUDGE_TEMPLATE.format(known=known, instruction=instruction[:3000], failures=failures, contrast=c,
                                               trajectory=trajectory)


def parse_judgement(text: str) -> dict[str, Any]:
    """解析判官的 JSON；格式不对就抛 ValueError（这一条记为"判官失败"，不猜）。"""
    t = re.sub(r"```(?:json)?", "", text or "")
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("no JSON object")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict) or any(k not in obj for k in REQUIRED):
        raise ValueError(f"missing keys {[k for k in REQUIRED if k not in (obj or {})]}")
    cat = str(obj["category"]).strip()
    if cat != "new" and cat not in KNOWN_EN:
        raise ValueError(f"unknown category {cat!r}")
    if cat == "new":
        nc = str(obj.get("new_category") or "").strip().lower()
        obj["new_category"] = nc if _SNAKE.match(nc) else "unnamed"
    obj["category"] = cat
    obj["harness_fixable"] = str(obj["harness_fixable"]).strip().lower()
    return obj


def agree(a: dict | None, b: dict | None) -> dict[str, Any]:
    """两家判官对同一条轨迹：同一个已知模式 → 采信；都说 new → 进新毛病池；其余 → 有分歧，交给人。"""
    if not a or not b:
        return {"status": "judge_failed"}
    if a["category"] == b["category"] == "new":
        return {"status": "new", "behaviors": [a["behavior"], b["behavior"]], "names": [a["new_category"], b["new_category"]],
                "fixable": [a["harness_fixable"], b["harness_fixable"]]}
    if a["category"] == b["category"]:
        return {"status": "known", "category": a["category"], "fixable": [a["harness_fixable"], b["harness_fixable"]]}
    return {"status": "disputed", "categories": [a["category"], b["category"]], "behaviors": [a["behavior"], b["behavior"]]}


CLUSTER_SYSTEM = "You group failure descriptions of a terminal coding agent into a few general behavior categories."

CLUSTER_TEMPLATE = """Each item below is one failed attempt, described independently by two reviewers. Group the items into at most {k}
categories of agent BEHAVIOR. Every item goes into exactly one category (use "other" for leftovers). Names and definitions must be
general (no file names, values or anything specific to one task).

For each category also say how a fixed program could detect it from the trajectory alone (the commands the agent sent and the
terminal output it saw), so that the category can be counted on future runs without an LLM.

ITEMS:
{items}

Return ONLY a JSON object:
{{"categories": [{{"name": "snake_case", "definition": "<at most 40 words>", "items": [<item numbers>],
   "detection_rule": "<how a program could recognise it from commands and outputs>", "harness_fixable": "<yes | no | unsure>"}}]}}"""


def cluster_prompt(new_items: list[dict], k: int = 6) -> tuple[str, str]:
    items = "\n".join(f"{i}. A: {it['behaviors'][0]} | B: {it['behaviors'][1]}" for i, it in enumerate(new_items, 1))
    return CLUSTER_SYSTEM, CLUSTER_TEMPLATE.format(k=k, items=items)


def parse_clusters(text: str, n_items: int) -> list[dict[str, Any]]:
    t = re.sub(r"```(?:json)?", "", text or "")
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("no JSON object")
    cats = json.loads(m.group(0)).get("categories")
    if not isinstance(cats, list):
        raise ValueError("categories is not a list")
    seen: set[int] = set()
    out = []
    for c in cats:
        if not isinstance(c, dict):
            continue
        idx = sorted({int(i) for i in c.get("items") or [] if str(i).isdigit() and 1 <= int(i) <= n_items} - seen)
        seen |= set(idx)
        out.append({"name": str(c.get("name", "unnamed")), "definition": str(c.get("definition", "")), "items": idx,
                    "detection_rule": str(c.get("detection_rule", "")), "harness_fixable": str(c.get("harness_fixable", ""))})
    return out


_APPEND_HINT = re.compile(r"append|line[- ]by[- ]line|one line (at a time|per)|echo\b.*>>|>>|piecemeal|incremental(ly)? writ", re.I)


def rediscovered_append(clusters: list[dict], items: list[dict]) -> dict[str, Any]:
    """找回测试。items = [{"behaviors": [两家判官的描述], "truth": 这条 trial 规则上是不是逐行追加（append_turns ≥ 10）}]。
    召回 = 真有逐行追加的 trial 里，至少一家判官的描述提到它的比例。这些 trial 多半撞轮数上限，判官可能只写"轮数用完"，
    所以看全部描述，不只看新毛病池。召回 ≥ 50%，或者有一类新毛病说的就是它，算找回来了。"""
    hit_c = [c["name"] for c in clusters if _APPEND_HINT.search(c["name"] + " " + c["definition"])]
    truth = [it for it in items if it.get("truth")]
    hits = sum(1 for it in truth if any(_APPEND_HINT.search(b or "") for b in it.get("behaviors") or []))
    false_hits = sum(1 for it in items if not it.get("truth") and any(_APPEND_HINT.search(b or "") for b in it.get("behaviors") or []))
    recall = hits / len(truth) if truth else None
    return {"clusters": hit_c, "n_truth": len(truth), "recall": recall, "mentions_on_other_trials": false_hits,
            "found": bool(hit_c) or (recall is not None and recall >= 0.5)}
