# 归责表（模式级；δ = 8 pp；发生率 = 出现该模式的 trial / 全部可评 trial）

- 弱模型基线：e4-baseline-rerun；弱模型改动：e4-selfcheck；强模型基线：e4s-baseline；强模型改动：e4s-selfcheck

| 模式 | 弱·基线 | 弱·改动 | 强·基线 | 强·改动 | Δ换模型 | Δ换harness | 归责 |
|---|---|---|---|---|---|---|---|
| PREMATURE_COMPLETION | 26% | 22% | 12% | 11% | +14 | +4 | **MODEL** |
| SPEC_MISINTERPRETATION | 17% | 13% | 10% | 9% | +7 | +4 | **UNKNOWN(<δ)** |
| BUDGET_EXHAUSTED | 13% | 10% | 0% | 2% | +13 | +3 | **MODEL** |
| TRUNCATED_READ | 13% | 8% | 0% | 0% | +13 | +5 | **MODEL** |
| COMMAND_NOT_FOUND | 6% | 3% | 2% | 0% | +4 | +4 | **UNKNOWN(<δ)** |
| INSUFFICIENT_VERIFICATION | 6% | 5% | 2% | 2% | +4 | +1 | **UNKNOWN(<δ)** |
| POLLING | 5% | 5% | 2% | 2% | +3 | +0 | **UNKNOWN(<δ)** |
| INTEGRITY_SUSPECT | 3% | 0% | 0% | 2% | +3 | +3 | **UNKNOWN(<δ)** |
| TASK_UNDERSPECIFIED | 3% | 3% | 0% | 0% | +3 | +0 | **ENVIRONMENT/TASK** |
| CANNOT_JUDGE | 3% | 1% | 0% | 0% | +3 | +1 | **UNKNOWN(<δ)** |
| STUCK_AT_PROMPT | 1% | 0% | 0% | 0% | +1 | +1 | **UNKNOWN(<δ)** |
| ACKNOWLEDGED_BUT_IGNORED | 1% | 0% | 0% | 0% | +1 | +1 | **UNKNOWN(<δ)** |
| CAPABILITY | 1% | 3% | 0% | 0% | +1 | -1 | **UNKNOWN(<δ)** |
| GOAL_DRIFT | 0% | 1% | 0% | 0% | +0 | -1 | **UNKNOWN(<δ)** |

读法：Δ换模型 = 弱基线 − 强基线（正数 = 强模型少犯，说明是模型能力问题）；Δ换harness = 弱基线 − 弱改动（正数 = harness 改动减少了它）。
两者都 ≥ δ 记 MIXED，只有前者 MODEL，只有后者 HARNESS；都 < δ 的按标签类别归 ENVIRONMENT/TASK 或 UNKNOWN。
