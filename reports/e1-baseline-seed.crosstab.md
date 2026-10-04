## 判官主标签（39 条失败）

- SPEC_MISINTERPRETATION: 14（36%）
- BUDGET_EXHAUSTED: 10（26%）
- INSUFFICIENT_VERIFICATION: 8（21%）
- TASK_UNDERSPECIFIED: 3（8%）
- CAPABILITY: 2（5%）
- CANNOT_JUDGE: 2（5%）

## 按 TB 三大类

- Coherence: 14
- Execution: 10
- Verification: 8
- NONE: 4
- TASK: 3

## onset：判官标的起始轮位于轨迹的中位相对位置 0.67；前 1/3 就出问题的占 14%（Failure as a Process：失败起得早）

## 规则标签 × 判官主标签

| 规则 | BUDGET_EXHAUSTED | CANNOT_JUDGE | CAPABILITY | INSUFFICIENT_VERIFICATION | SPEC_MISINTERPRETATION | TASK_UNDERSPECIFIED |
|---|---|---|---|---|---|---|
| PREMATURE_COMPLETION |  | 2 |  | 8 | 12 | 3 |
| BUDGET_EXHAUSTED | 10 |  | 2 |  | 2 |  |
| TRUNCATED_READ | 5 | 1 |  |  | 5 |  |
| COMMAND_NOT_FOUND | 3 | 2 |  | 1 | 3 |  |
| POLLING |  |  | 1 | 1 |  | 1 |
| STUCK_AT_PROMPT |  |  |  |  | 1 |  |
