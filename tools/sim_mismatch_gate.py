"""离线模拟"能识别不一致的交卷检查"（P0 的 review 提案）：第一次宣布完成时，最近一次真正运行过东西的那一轮输出里有没有明确的失败信号。
只读第 1 轮已有轨迹，不调模型。输出：触发次数按最终通过 / 失败交叉统计，并打印例子供人工核对。"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/root/work/agent_harness")
from terminus2_patches.helpers import is_run_command  # noqa: E402

PROMPT_RE = re.compile(r"^\S*@[\w.-]*:[^\n]*[#$] ")      # 终端回显的提示符行（模型敲的命令）
FAIL_RE = re.compile(
    r"Traceback \(most recent call last\)|^\s*\w*(Error|Exception): |^E\s{2,}|\bFAILED\b|\b\d+ failed\b|AssertionError|"
    r"\bmismatch(es|ed)?\b|\bdoes not match\b|\bdo not match\b|\bnot equal\b|^Files .+ differ$|Connection refused|curl: \(\d+\)|"
    r"Segmentation fault|returned non-zero|exit (status|code):? *[1-9]", re.I | re.M)
DIFF_LINE_RE = re.compile(r"^([<>] |@@ |--- |\+\+\+ )", re.M)


def program_output(text: str) -> str:
    """去掉回显的命令行和 heredoc 输入行（以 '> ' 开头），只留程序真正打印的东西。"""
    keep, in_input = [], False
    for line in text.splitlines():
        if PROMPT_RE.match(line):
            in_input = True                      # 提示符之后紧跟的 "> " 行是命令的续行输入
            continue
        if in_input and line.startswith("> "):
            continue
        in_input = False
        keep.append(line)
    return "\n".join(keep)


def steps_of(traj):
    out = []
    for s in traj.get("steps") or []:
        if s.get("source") != "agent":
            continue
        cmds, claimed = [], False
        for tc in s.get("tool_calls") or []:
            if tc.get("function_name") == "bash_command":
                cmds.append(str((tc.get("arguments") or {}).get("keystrokes", "")))
            elif tc.get("function_name") == "mark_task_complete":
                claimed = True
        obs = "".join(str(r.get("content", "")) for r in ((s.get("observation") or {}).get("results") or []))
        out.append({"cmds": cmds, "out": obs, "claimed": claimed})
    return out


def fires(steps):
    """返回 (触发与否, 证据片段, 最近一次检查在第几轮)。只看第一次宣布完成。"""
    claim = next((i for i, s in enumerate(steps) if s["claimed"]), None)
    if claim is None:
        return None
    last = next((i for i in range(claim, -1, -1) if any(is_run_command(c) for c in steps[i]["cmds"])), None)
    if last is None:
        return (False, "", None)
    out = program_output(steps[last]["out"])
    m = FAIL_RE.search(out)
    if not m and any("diff" in c for c in steps[last]["cmds"]):
        m = DIFF_LINE_RE.search(out)
    if m:
        lo = max(0, m.start() - 80)
        return (True, out[lo:m.end() + 80].replace("\n", " ⏎ "), claim - last)
    return (False, "", claim - last)


res = Counter()
examples = {"fire_pass": [], "fire_fail": []}
for arm in ["base", "c04"]:
    rows = [json.loads(l) for l in open(f"/root/work/reports/loop/r1/{arm}/rows.jsonl")]
    for r in rows:
        if r.get("infra"):
            continue
        d = Path("/root/work/jobs") / r["job"] / r["trial"]
        try:
            traj = json.loads((d / "agent/trajectory.json").read_text())
        except Exception:
            continue
        f = fires(steps_of(traj))
        if f is None:
            res[(arm, "no_claim", r["passed"])] += 1
            continue
        hit, ev, gap = f
        res[(arm, "fire" if hit else "quiet", r["passed"])] += 1
        if hit:
            examples["fire_pass" if r["passed"] else "fire_fail"].append((r["trial"], gap, ev[:260]))

for arm in ["base", "c04"]:
    fp, ff = res[(arm, "fire", True)], res[(arm, "fire", False)]
    qp, qf = res[(arm, "quiet", True)], res[(arm, "quiet", False)]
    print(f"{arm}: claims {fp+ff+qp+qf} | fires on FAILED {ff} of {ff+qf} failed claims ({100*ff/max(1,ff+qf):.0f}%) | "
          f"fires on PASSED {fp} of {fp+qp} passed claims ({100*fp/max(1,fp+qp):.0f}%) | precision {100*ff/max(1,ff+fp):.0f}% | "
          f"no claim: {res[(arm,'no_claim',False)]+res[(arm,'no_claim',True)]}")
print("\n== fired on PASSED trials (would cost a bounce):")
for e in examples["fire_pass"][:12]:
    print(" ", e)
print("\n== fired on FAILED trials (sample):")
for e in examples["fire_fail"][:15]:
    print(" ", e)
