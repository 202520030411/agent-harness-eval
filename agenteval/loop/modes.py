"""闭环观察的失败模式：每个模式有判定、分母、先验归责（来自已做过的对照实验）和可动的开关。

先验归责只来自已经跑完、写进 decisions / QWEN_PLAN 的对照实验，不在开发集上重新挑（避免用测试集选改动）：
- HARNESS：换 harness 能显著改变它，换模型改变不大；
- MODEL：任何 harness 下都在，harness 改动压不下去；
- MIXED：两边都动；UNKNOWN：证据不足或不是这个模型特有。
行（row）的字段由 tools/loop_cycle.observe_trial 生成。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Mode:
    id: str
    label: str
    test: Callable[[dict], bool]
    among: str                     # all = 占全部可评 trial；failed = 占失败 trial
    prior: str                     # HARNESS | MODEL | MIXED | UNKNOWN
    evidence: str
    levers: tuple = ()             # 可能有用的 auto 开关（提议模型的出发点，不是结论）


def _labels(r: dict) -> set:
    return set(r.get("rule_labels") or ())


MODES: list[Mode] = [
    Mode("format_error", "出现过格式错误（回复不是 harness 要的 JSON）", lambda r: (r.get("n_parse_err") or 0) > 0, "all", "HARNESS",
         "Qwen 四臂：H0 57% → H1 8%（宽松解析）→ H3 0%（原生工具调用）；D-055 / QWEN_PLAN §2–3", ("interface_fixes",)),
    Mode("format_stuck", "最后 3 步都是格式错误（卡死）", lambda r: bool(r.get("json_loop_end")), "all", "HARNESS",
         "同上；阶段 0 3/90", ("interface_fixes",)),
    Mode("turn_cap", "跑满轮数上限", lambda r: (r.get("turns") or 0) >= (r.get("max_turns") or 100), "all", "MIXED",
         "Qwen 四臂：H0 9 → H1 1（多半是写坏 JSON 或把代码拆成一行行追加把轮数耗光）", ("interface_fixes", "deliverable_checkpoint")),
    Mode("timeout", "超时（agent 时限用完）", lambda r: bool(r.get("timeout")), "all", "MIXED",
         "Seed：验证类改动把超时推高（grader_check 9→34）；adaptive_wait 不改通过率、省轮数", ("adaptive_wait", "deliverable_checkpoint")),
    Mode("polling", "连续空等待（POLLING）", lambda r: "POLLING" in _labels(r) or (r.get("polling_turns") or 0) >= 3, "failed", "HARNESS",
         "Seed E4：adaptive_wait 让空等待轮 −27%、失败里 POLLING 13%→4%", ("adaptive_wait",)),
    Mode("stuck_at_prompt", "卡在交互提示（分页器、y/N、续行）", lambda r: "STUCK_AT_PROMPT" in _labels(r), "failed", "HARNESS",
         "taxonomy：交互提示归 harness；adaptive_wait 识别提示、interface_fixes 续行提示", ("adaptive_wait", "interface_fixes")),
    Mode("loop", "重复同一个失败动作（LOOP）", lambda r: "LOOP" in _labels(r), "failed", "MIXED",
         "Seed 上 stuck_reminder 从未触发（已退役，D-039）", ()),
    Mode("truncated_read", "读类命令的输出被截断（TRUNCATED_READ）", lambda r: "TRUNCATED_READ" in _labels(r), "failed", "MIXED",
         "证据互相矛盾：README 归责节说换强模型后消失、改 harness 不变；但 E4 adaptive_wait 臂失败里占比 33%→14%（未同时跑，约 10→4 条）；"
         "D-043：判官给的证据 0/11 提到截断 → 更像伴随症状而不是原因。规则本身把它标成 harness 侧候选", ("adaptive_wait",)),
    Mode("command_not_found", "用了环境里没有的命令", lambda r: bool(r.get("cnf")), "all", "UNKNOWN",
         "Qwen 40% / gpt-6-sol 同规则 31%：不是 Qwen 特有；开跑前环境探测没用（40%→38%）", ("interface_fixes",)),
    Mode("echo_theater", "用 echo 打印“完成”代替真正的检查", lambda r: bool(r.get("echo_theater")), "failed", "HARNESS",
         "接口产物：Terminus 里失败 trial 59%，qwen-code 2%；交卷把关压不下去（42%→49%）——要靠新机制（需人审）", ("completion_gate",)),
    Mode("false_success", "明知没做成仍宣布完成", lambda r: bool(r.get("false_success")), "failed", "MODEL",
         "任何 harness 下都占失败的 23–31%，交卷把关压不下去 → 训练目标（QWEN_PLAN §3）", ()),
    Mode("claim_without_run", "宣布完成前最后一次改文件后没运行过任何东西", lambda r: bool(r.get("no_run_before_claim")), "all", "MIXED",
         "H2 交卷把关打回 37/120，只有 4 个最终通过：能逼它查，查出来修不好", ("completion_gate", "verifier_gate")),
    Mode("premature_completion", "宣布完成但判分失败（PREMATURE_COMPLETION）", lambda r: "PREMATURE_COMPLETION" in _labels(r), "failed", "MIXED",
         "Seed：规则层 64% 的失败；判官把它拆成误读 / 验证不足 / 题面不清", ("completion_gate", "verifier_gate", "task_contract")),
    Mode("budget_exhausted", "没宣布完成就用完预算（BUDGET_EXHAUSTED）", lambda r: "BUDGET_EXHAUSTED" in _labels(r), "failed", "MIXED",
         "Seed 归责：强模型上消失、改 harness 不变 → 偏模型；交付检查点让无交付 11→6", ("deliverable_checkpoint", "adaptive_wait")),
    Mode("line_by_line_write", "逐行追加写文件（≥10 轮 echo/printf >>）", lambda r: (r.get("append_turns") or 0) >= 10, "all", "UNKNOWN",
         "闭环第 1 轮读日志加入（不是对照实验得出的）：Qwen 在合成题上 17–26% 的 trial，约 230 个里只 1 个通过；H0 vs H2 同批 21% vs 17%"
         "（现有开关压不下去）；SFT / RL 后 18–23%（训练也没压下去）；gpt-6-sol、Seed 同题 0%；TB 上 2–3%。还没有针对它的 harness 对照，"
         "所以先验记 UNKNOWN：进人工队列，由人决定是否试 append_nudge（D-085）", ("append_nudge",)),
    Mode("integrity_suspect", "碰过判题文件或日志（作弊嫌疑）", lambda r: "INTEGRITY_SUSPECT" in _labels(r), "all", "MODEL",
         "规则层；通过 + 嫌疑 = 可能的 reward hacking，送人看", ()),
]
MODE_BY_ID = {m.id: m for m in MODES}


def mode_table(rows: list[dict[str, Any]], max_examples: int = 3) -> list[dict[str, Any]]:
    """每个模式：出现次数、占分母的比例、占失败 trial 的比例、涉及几道题、最多几个例子（按 trial 名排序取前几个，
    不是随机样本；只写进 observe.json，不给提议模型看）。基础设施故障不计。"""
    ev = [r for r in rows if not r.get("infra")]
    failed = [r for r in ev if not r.get("passed")]
    out = []
    for m in MODES:
        denom = ev if m.among == "all" else failed
        hits = [r for r in denom if m.test(r)]
        hits_failed = [r for r in failed if m.test(r)]
        out.append({
            "mode": m.id, "label": m.label, "among": m.among, "prior": m.prior, "evidence": m.evidence, "levers": list(m.levers),
            "n": len(hits), "denominator": len(denom), "rate": len(hits) / len(denom) if denom else 0.0,
            "share_of_failures": len(hits_failed) / len(failed) if failed else 0.0,
            "n_tasks": len({r["task"] for r in hits}),
            "examples": [r["trial"] for r in sorted(hits, key=lambda r: r["trial"])[:max_examples]],
        })
    return out


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ev = [r for r in rows if not r.get("infra")]
    tasks = {r["task"] for r in ev}
    passed = sum(1 for r in ev if r.get("passed"))

    def mean(key):
        xs = [r[key] for r in ev if r.get(key) is not None]
        return sum(xs) / len(xs) if xs else None
    return {"n_trials": len(rows), "n_infra": len(rows) - len(ev), "n_tasks": len(tasks), "pass_rate": passed / len(ev) if ev else None,
            "timeouts": sum(1 for r in ev if r.get("timeout")), "mean_turns": mean("turns"), "mean_minutes": mean("minutes"),
            "mean_tokens_in": mean("tokens_in")}
