"""交接包（taxonomy.md §4 末尾）：改动后仍存在的 MODEL / MIXED 模式 → 给模型团队的 BadPattern 描述。
每个模式：定义、跨配置发生率、3–5 条代表轨迹（trial_id + 起始轮 + 该轮模型自述摘录）、我们试过的 harness 缓解及结果、建议补的题型。"""
from __future__ import annotations

from agenteval.schemas import TrialRecord

MITIGATIONS = {   # 模式 → (试过的 harness 改动, E4 结果一句话)
    "PREMATURE_COMPLETION": [("verifier_gate=self_check", "失败里 PREMATURE_COMPLETION 未明显减少；pass +6.4 pp（<δ），成本 +35%"),
                             ("verifier_gate=auditor", "22 次打回本身都对、但模型补不完，7 条推到超时；pass +0.0"),
                             ("task_contract", "PREMATURE 26%→17%/trial，主要是 SPEC 类失败减少带来的")],
    "BUDGET_EXHAUSTED": [("budget_hint（hygiene 臂）", "无效（−1.3 pp）；轮数没有变化"),
                         ("adaptive_wait", "空等待轮 −27%、token −11%，但通过率不涨：省下的轮没有转成进展")],
    "TRUNCATED_READ": [("adaptive_wait", "失败里 TRUNCATED_READ 33%→14%（省了轮次但没省错误）"),
                       ("read_file_tool", "未实现（基线 TRUNCATED_READ 在失败里 33%，按 H8 门槛本应做；留作下一步）")],
    "SPEC_MISINTERPRETATION": [("task_contract", "13→9（失败条数）；模糊题 +13.9 pp；强模型上无收益 → 拐杖")],
}
SUGGESTED_TASKS = {
    "PREMATURE_COMPLETION": "带隐藏验收标准、且跑一下测试就能自检的题（让先验证再声称完成有可学的回报）",
    "BUDGET_EXHAUSTED": "需要 20+ 轮、中途有可复用中间产物的长任务；奖励里加轮次/token 惩罚",
    "TRUNCATED_READ": "输出超过一屏的文件/日志检索题，正确答案在被截断的部分之后",
    "SPEC_MISINTERPRETATION": "题面故意留一处可澄清的歧义，环境里放着能消歧的线索（示例文件、测试桩）",
}


def _excerpt(t: TrialRecord, onset: int | None) -> str:
    steps = [s for s in t.agent_steps if s.source == "agent"]
    if not steps:
        return ""
    s = next((x for x in steps if onset is not None and x.step_id >= onset), steps[-1])
    return s.message.strip().replace("\n", " ")[:220]


def handoff(pattern: str, rows: list[dict], weak_base: list[TrialRecord], judge: dict[str, dict], n_examples: int = 4) -> str:
    row = next((r for r in rows if r["pattern"] == pattern), None)
    ex = []
    for t in weak_base:
        if t.passed or t.status not in ("ok", "agent_timeout"):
            continue
        names = {l.name for l in t.labels if l.kind == "failure"}
        j = judge.get(t.trial_id, {})
        if pattern in names or j.get("judge_primary") == pattern:
            onset = next((l.onset_step for l in t.labels if l.name == pattern and l.onset_step), None) or j.get("judge_onset")
            ex.append((t, onset))
    ex = ex[:n_examples]
    L = [f"## {pattern}（归责：{row['blame'] if row else '?'}）", ""]
    if row:
        L.append(f"发生率（占全部可评 trial）：弱模型基线 {100*row['weak_base']:.0f}% → 改 harness 后 {100*row['weak_mod']:.0f}%；强模型基线 {100*row['strong_base']:.0f}%。")
    L += ["", "**代表轨迹**（`harbor view` 可回放）：", ""]
    for t, onset in ex:
        L.append(f"- `{t.trial_id}`（{t.task_name}，{t.n_episodes} 轮，起始轮 {onset or '?'}）：“{_excerpt(t, onset)}”")
    L += ["", "**我们在 harness 侧试过的缓解：**", ""]
    for m, r in MITIGATIONS.get(pattern, []):
        L.append(f"- {m}：{r}")
    L += ["", f"**建议模型侧补的题型：** {SUGGESTED_TASKS.get(pattern, '—')}", ""]
    return "\n".join(L)


def render_all(rows: list[dict], weak_base: list[TrialRecord], judge: dict[str, dict]) -> str:
    keep = [r["pattern"] for r in rows if r["blame"] in ("MODEL", "MIXED")]
    head = ["# 交接包：改 harness 之后仍归责到模型的失败模式", "",
            "粒度是模式级（跨配置发生率），不是单条 trial 的因果。每个模式给 3–5 条轨迹、试过的 harness 缓解、建议题型。", ""]
    return "\n".join(head + [handoff(p, rows, weak_base, judge) for p in keep])
