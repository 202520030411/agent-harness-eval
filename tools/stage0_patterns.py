"""阶段 0：把读轨迹时看到的三种毛病写成规则，三个模型同一口径统计（TB 2.1 干净题）。

  json_ctrl      出现过 “Invalid JSON: Invalid control character”（JSON 字符串里直接换行 / 控制字符）
  json_loop_end  最后 3 个 agent 步的观察全是解析错误（卡死到结束）
  false_success  失败且宣布完成，最后 3 个 agent 步的分析里有承认没做成的措辞（haven't / couldn't / still not / placeholder …）
  echo_theater   最后 5 个 agent 步里用 echo 打印“✓ / complete / success / verified / fulfilled”代替检查
用法：PYTHONPATH=. .venv/bin/python tools/stage0_patterns.py --out /root/work/reports/stage0/patterns.md
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARSE_ERR = re.compile(r"Previous response had parsing errors|ERROR: Invalid JSON|ERROR: No valid JSON|ERROR: Missing required fields")
CTRL_ERR = re.compile(r"Invalid control character")
ADMIT = re.compile(r"(haven't|have not|hasn't|couldn't|could not|unable to|not (yet )?(been )?able|still not|not meeting|doesn't meet|don't meet|"
                   r"did not (succeed|work|pass)|didn't (succeed|work|pass)|placeholder|dummy value|although|while (we|i) (couldn't|could not|haven't|were unable|was unable)|"
                   r"difficult(y|ies) with|not (fully|completely) (eliminate|solve|meet|pass))", re.I)
THEATER = re.compile(r"echo[^\n]*(✓|✔|complete|success|verified|fulfilled|all requirements|passed)", re.I)


def clean_tasks() -> set[str]:
    return {t.strip() for t in (ROOT / "experiments/task_list_tb21_clean.txt").read_text().splitlines() if t.strip() and not t.startswith("#")}


def trial_rows(job: str, keep: set[str]):
    for d in sorted(Path(job).glob("*/")):
        try:
            r = json.load(open(d / "result.json"))
            t = json.load(open(d / "agent" / "trajectory.json"))
        except Exception:  # noqa: BLE001
            continue
        task = r["task_name"].split("/")[-1]
        if task not in keep:
            continue
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        steps = [s for s in t["steps"] if s.get("source") == "agent"]
        obs = [((s.get("observation") or {}).get("results") or [{}])[0].get("content") or "" for s in steps]
        msgs = [s.get("message") or "" for s in steps]
        keys = [[(tc.get("arguments") or {}).get("keystrokes", "") for tc in (s.get("tool_calls") or [])] for s in steps]
        declared = "task_complete" in json.dumps(t["steps"][-3:]) or any("mark the task as complete" in o for o in obs[-3:])
        passed = bool(rew and rew >= 1)
        yield {
            "job": Path(job).name, "trial": d.name, "task": task, "passed": passed,
            "json_ctrl": any(CTRL_ERR.search(o) for o in obs),
            "n_parse_err": sum(1 for o in obs if PARSE_ERR.search(o)),
            "json_loop_end": len(obs) >= 3 and all(PARSE_ERR.search(o) for o in obs[-3:]),
            "false_success": (not passed) and declared and any(ADMIT.search(m) for m in msgs[-3:]),
            "echo_theater": any(THEATER.search(k) for ks in keys[-5:] for k in ks),
            "turns": len(steps),
        }


def main(a):
    keep = clean_tasks()
    groups = {"Qwen3-Coder-30B-A3B": a.qwen, "Seed lite": a.seed, "gpt-6-sol": a.strong}
    data = {name: [row for j in jobs for row in trial_rows(j, keep)] for name, jobs in groups.items()}
    lines = ["# 阶段 0：三种毛病的规则统计（TB 2.1 干净题，同一口径）", "",
             "| 指标 | " + " | ".join(groups) + " |", "|---|" + "---|" * len(groups)]

    def pct(rows, key, among=None):
        base = [r for r in rows if among is None or among(r)]
        return f"{sum(r[key] for r in base)}/{len(base)} ({100 * sum(r[key] for r in base) / max(1, len(base)):.0f}%)"

    for label, key, among in (("出现过 JSON 控制字符错误（全部 trial）", "json_ctrl", None),
                              ("最后 3 步全是解析错误、卡死到结束（全部 trial）", "json_loop_end", None),
                              ("明知没做成仍宣布完成（失败 trial）", "false_success", lambda r: not r["passed"]),
                              ("用 echo 打印代替检查（全部 trial）", "echo_theater", None),
                              ("用 echo 打印代替检查（失败 trial）", "echo_theater", lambda r: not r["passed"])):
        lines.append(f"| {label} | " + " | ".join(pct(data[n], key, among) for n in groups) + " |")
    lines.append("| 平均解析错误轮数 / trial | " + " | ".join(f"{sum(r['n_parse_err'] for r in data[n]) / max(1, len(data[n])):.1f}" for n in groups) + " |")
    lines.append("| 通过率 | " + " | ".join(pct(data[n], "passed") for n in groups) + " |")

    q = data["Qwen3-Coder-30B-A3B"]
    lines += ["", "## Qwen 的例子", ""]
    for key in ("json_loop_end", "false_success", "echo_theater"):
        ex = [r["trial"] for r in q if r[key] and not r["passed"]][:6]
        lines.append(f"- {key}：" + "、".join(f"`{x}`" for x in ex))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n")
    Path(a.out).with_suffix(".jsonl").write_text("\n".join(json.dumps(r) for n in groups for r in data[n]) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--qwen", nargs="+", default=["/root/work/jobs/stage0-qwen-coder30b-tb21clean"])
    ap.add_argument("--seed", nargs="+", default=["/root/work/jobs/h17-baseline", "/root/work/jobs/e4p-baseline"])
    ap.add_argument("--strong", nargs="+", default=["/root/work/jobs/e2-baseline-strong", "/root/work/jobs/e4s-baseline"])
    ap.add_argument("--out", default="/root/work/reports/stage0/patterns.md")
    main(ap.parse_args())
