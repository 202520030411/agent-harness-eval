# 归责表（模式级；δ = 8 pp；发生率 = 出现该模式的 trial / 全部可评 trial）

- 弱模型基线：e4-baseline-rerun；弱模型改动：e4-contract；强模型基线：e4s-baseline；强模型改动：e4s-contract

| 模式 | 弱·基线 | 弱·改动 | 强·基线 | 强·改动 | Δ换模型 | Δ换harness | 归责 |
|---|---|---|---|---|---|---|---|
| PREMATURE_COMPLETION | 26% | 17% | 12% | 13% | +14 | +9 | **MIXED** |
| SPEC_MISINTERPRETATION | 17% | 12% | 10% | 7% | +7 | +5 | **UNKNOWN(<δ)** |
| BUDGET_EXHAUSTED | 13% | 14% | 0% | 0% | +13 | -1 | **MODEL** |
| TRUNCATED_READ | 13% | 9% | 0% | 0% | +13 | +4 | **MODEL** |
| INSUFFICIENT_VERIFICATION | 6% | 4% | 2% | 2% | +4 | +3 | **UNKNOWN(<δ)** |
| COMMAND_NOT_FOUND | 6% | 3% | 2% | 2% | +4 | +4 | **UNKNOWN(<δ)** |
| POLLING | 5% | 4% | 2% | 0% | +3 | +1 | **UNKNOWN(<δ)** |
| TASK_UNDERSPECIFIED | 3% | 1% | 0% | 4% | +3 | +1 | **ENVIRONMENT/TASK** |
| INTEGRITY_SUSPECT | 3% | 3% | 0% | 0% | +3 | +0 | **UNKNOWN(<δ)** |
| CANNOT_JUDGE | 3% | 1% | 0% | 0% | +3 | +1 | **UNKNOWN(<δ)** |
| STUCK_AT_PROMPT | 1% | 0% | 0% | 0% | +1 | +1 | **UNKNOWN(<δ)** |
| ACKNOWLEDGED_BUT_IGNORED | 1% | 0% | 0% | 0% | +1 | +1 | **UNKNOWN(<δ)** |
| CAPABILITY | 1% | 4% | 0% | 0% | +1 | -3 | **UNKNOWN(<δ)** |

读法：Δ换模型 = 弱基线 − 强基线（正数 = 强模型少犯，说明是模型能力问题）；Δ换harness = 弱基线 − 弱改动（正数 = harness 改动减少了它）。
两者都 ≥ δ 记 MIXED，只有前者 MODEL，只有后者 HARNESS；都 < δ 的按标签类别归 ENVIRONMENT/TASK 或 UNKNOWN。
