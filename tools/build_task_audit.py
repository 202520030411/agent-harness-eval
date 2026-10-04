"""TB2.1 任务质量审计骨架：每题一行，汇总 clarity 评分、弱/强模型通过率、判官标签与“题面缺什么”原文、改题实验结果，自动给一个待人工确认的缺陷类别。
用法：python tools/build_task_audit.py  → docs/task_audit.md + reports/task_audit.csv（human_* 列留空给人填）"""
import csv, json, collections, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tasks = [t for t in (ROOT / "experiments/task_list.txt").read_text().split() if t]
clarity = {json.loads(l)["task"]: json.loads(l) for l in open(ROOT / "reports/clarity.jsonl")}

def rates(path):
    d = collections.defaultdict(list)
    for l in open(path):
        r = json.loads(l)
        if r["status"] in ("ok", "agent_timeout"): d[r["task_name"]].append(int(r["reward"] >= 1))
    return d
weak = rates(ROOT / "reports/figdata/e1-baseline-seed.trials.jsonl")
weak4 = rates(ROOT / "reports/figdata/e4-baseline-rerun.trials.jsonl")
strong = rates(ROOT / "reports/figdata/e2-baseline-strong.trials.jsonl")
e8 = rates(ROOT / "reports/e8/analysis/trials.jsonl") if (ROOT / "reports/e8/analysis/trials.jsonl").exists() else {}
e8b = rates(ROOT / "reports/e4t/e8b-rewrite-seed.analysis/trials.jsonl") if (ROOT / "reports/e4t/e8b-rewrite-seed.analysis/trials.jsonl").exists() else {}

judge = collections.defaultdict(list); notes = collections.defaultdict(list)
for l in open(ROOT / "reports/figdata/e1-baseline-seed.judge.jsonl"):
    r = json.loads(l); judge[r["task"]].append(r["judge_primary"])
    m = re.search(r"^Underspecification:\s*(.+)$", r["judge_raw"], re.M)
    if m and not m.group(1).strip().lower().startswith("none"): notes[r["task"]].append(m.group(1).strip())

# 已由实验定案的（E8 / E8b / 人工核查）
SETTLED = {
    "extract-elf": ("接口约定", "题面示例地址 4194304 与参考实现（用段头 sh_addr、不加 PIE 偏移）对给定的 PIE 文件矛盾；写明约定后 0/6 → 3/3"),
    "cancel-async-tasks": ("接口约定", "取消语义（已启动的取消、排队的不启动、finally 自身会 await）题面未说；写明后 2/6 → 3/3"),
    "dna-insert": ("接口约定 + 环境工具", "插入边界有两种等价切法、验证器用靠左的；环境未装 oligotm，apt 版本与验证器版本对同一序列判定相反；两者补齐后 3/3"),
    "raman-fitting": ("领域知识 + 接口约定", "x 轴需 1e7/x 换算（领域知识，题面提示不够）；给了换算后峰位全对，仍卡在题面未给的 2D 拟合窗口（E8b 0/3）"),
    "chess-best-move": ("无（能力）", "写明“best = 一步将死、可多解”后仍 2/3，失败都是看图认子"),
    "configure-git-webserver": ("接口约定 / 测试契约", "题面说“登录不用你管”，verify.sh 却要求存在 user 账号并可 ssh；模型据此没建账号 → clone 失败 404"),
    "sanitize-git-repo": ("测试契约", "测试写死原始提交 SHA 做 diff；题面“确保仓库里没有敏感值”合理导向重写历史，重写 + gc 后 SHA 消失"),
    "largest-eigenval": ("环境工具（易抖动测试）", "速度测试逐尺寸起子进程跑 100 次取中位数、单次无重试；模型实现 5×5/7×7 为 24/25 µs，6×6 突跳 59 µs（参考 43）→ 那一刻 CPU 被抢；建议测试改为多轮取最优或重试"),
    "path-tracing-reverse": ("无（预算/能力）", "对照题，题面清楚，6/6 失败全是 BUDGET_EXHAUSTED"),
    "sqlite-with-gcov": ("无（验证不足）", "“放到 PATH 里”清楚；模型把 PATH 写进 profile.d/.bashrc 对子进程无效，自检在同一 shell 里 export 后 which，等于没查"),
    "adaptive-rejection-sampler": ("疑似接口约定（次要）", "人工定案：验证不足为主（自测 5000 样本未计时）；v3 判官指出评分超时时长题面未说，记次因。改题可加“评分时限”一句"),
    "count-dataset-tokens": ("无（预算）", "人工定案 BUDGET_EXHAUSTED：有候选计数却没先写答案文件；交付检查点针对的正是这类"),
    "headless-terminal": ("无（验证不足）", "人工定案：只用 python REPL 测交互程序，题面明说要支持交互程序；pyte 处理私有转义序列有 bug 记次因"),
    "pytorch-model-cli": ("无（验证不足）", "三家判官一致 INSUFFICIENT_VERIFICATION；v3 另指出预处理把 PNG alpha 通道算进灰度（bug），属能力/验证"),
    "overfull-hbox": ("无（验证不足）", "规则清楚；重放改动用测试逐词检查：#1 违规是介词 in→at（模型的修复 sed 未命中、未验证），#2 是冠词 an→a；两家判官指控的“不合法同义词”经核对全在表里"),
}

def auto_class(t):
    if t in SETTLED: return SETTLED[t][0], SETTLED[t][1], "已验证"
    c = clarity.get(t, {}); sev = max(c.get("intent_clarity", 0), c.get("target_certainty", 0))
    und = judge[t].count("TASK_UNDERSPECIFIED"); spec = judge[t].count("SPEC_MISINTERPRETATION")
    w = weak.get(t, []); s = strong.get(t, [])
    if not w or sum(w) == len(w): return "无迹象", "弱模型全过", "—"
    if und or (sev >= 2 and spec): return "疑似接口约定", "; ".join(notes[t][:2]) or c.get("missing", ""), "待验证（改题重跑）"
    if sev >= 2: return "疑似（清晰度评分低但失败原因不在题面）", c.get("missing", ""), "待人工"
    if s and sum(s) == len(s) and sum(w) < len(w): return "无迹象（强模型能推断）", c.get("missing", "") or "—", "—"
    return "无迹象", c.get("missing", "") or "—", "—"

rows = []
for t in tasks:
    c = clarity.get(t, {}); w = weak.get(t, []); w4 = weak4.get(t, []); s = strong.get(t, [])
    cls, ev, status = auto_class(t)
    rows.append({"task": t, "intent_0_3": c.get("intent_clarity", ""), "target_0_3": c.get("target_certainty", ""),
                 "weak_E1": f"{sum(w)}/{len(w)}" if w else "", "weak_E4": f"{sum(w4)}/{len(w4)}" if w4 else "", "strong_E2": f"{sum(s)}/{len(s)}" if s else "",
                 "judge_labels": ", ".join(f"{k}×{v}" for k, v in collections.Counter(judge[t]).most_common()),
                 "rewrite": (f"E8 {sum(e8[t])}/{len(e8[t])}" if t in e8 else "") + (f"; E8b {sum(e8b[t])}/{len(e8b[t])}" if t in e8b else ""),
                 "auto_class": cls, "evidence": ev, "status": status,
                 "judge_underspec_notes": " | ".join(notes[t]), "clarity_missing": c.get("missing", ""),
                 "human_class": "", "human_note": "", "suggested_fix": ""})
# 顺序：已验证 → 疑似 → 无迹象
order = {"已验证": 0, "待验证（改题重跑）": 1, "待人工": 2}
rows.sort(key=lambda r: (order.get(r["status"], 3), r["task"]))
with open(ROOT / "reports/task_audit.csv", "w", newline="", encoding="utf-8") as f:
    wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys())); wtr.writeheader(); wtr.writerows(rows)

L = ["# Terminal-Bench 2.1 任务质量审计（骨架，2026-09-24）", "",
     "对象：本项目用的 41 道题。每题给出：题面清晰度评分（0 无问题 … 3 严重）、弱模型 Seed lite 通过率（E1 / E4 同批）、强模型 gpt-6-sol 通过率（E2，k=1）、失败的判官主标签、改题实验结果，以及一个**待人工确认**的缺陷类别。",
     "", "缺陷类别定义（D-034）：**接口约定** = 题面没说但验收依赖的约定（地址基址、边界、信号语义、输出格式），改题面就能修；**领域知识** = 需要行业知识才能推断，题面提示也难救；**环境工具** = 验证器依赖的工具/版本环境里没有或不一致；**测试契约** = 题面与测试脚本的前提不一致；**无迹象** = 失败原因不在题面。", "",
     "| 题 | 清晰度 意图/目标 | Seed E1 | Seed E4 | gpt-6-sol | 失败判官标签 | 改题实验 | 自动类别 | 状态 |", "|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    L.append(f"| {r['task']} | {r['intent_0_3']}/{r['target_0_3']} | {r['weak_E1']} | {r['weak_E4']} | {r['strong_E2']} | {r['judge_labels'] or '—'} | {r['rewrite'] or '—'} | {r['auto_class']} | {r['status']} |")
L += ["", "## 逐题证据", ""]
for r in rows:
    if r["status"] == "—" and not r["judge_underspec_notes"]: continue
    L += [f"### {r['task']}", f"- 自动类别：**{r['auto_class']}**（{r['status']}）", f"- 证据：{r['evidence']}"]
    if r["clarity_missing"] and r["clarity_missing"] != "none": L.append(f"- 清晰度判官认为缺：{r['clarity_missing']}")
    if r["judge_underspec_notes"]: L.append(f"- 归因判官的“题面缺什么”原文：{r['judge_underspec_notes']}")
    rw = ROOT / "experiments/e8_rewrites" / r["task"] / "instruction.md"
    if rw.exists(): L.append(f"- 已有改写：`experiments/e8_rewrites/{r['task']}/instruction.md`")
    L.append("- 人工判断：（待填）"); L.append("")
(ROOT / "docs/task_audit.md").write_text("\n".join(L) + "\n")
print(len(rows), "tasks;", collections.Counter(r["status"] for r in rows))
