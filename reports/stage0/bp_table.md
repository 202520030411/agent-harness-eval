# 阶段 0：Qwen3-Coder-30B-A3B 的 bad pattern 表（TB 2.1 干净题 30 道）

| 模型 | trial | 通过率 |
|---|---|---|
| Qwen3-Coder-30B-A3B | 90 | 20.0% |
| Seed lite | 180 | 81.1% |
| gpt-6-sol | 61 | 95.1% |

## 1. 规则标签发生率（占全部 trial）

| 标签 | Qwen | Seed | gpt-6-sol | Qwen − gpt-6-sol | 模型侧（≥ 8 pp） |
|---|---|---|---|---|---|
| PREMATURE_COMPLETION | 69% | 8% | 5% | +64 | 是 |
| COMMAND_NOT_FOUND | 23% | 1% | 2% | +22 | 是 |
| TRUNCATED_READ | 3% | 6% | 2% | +2 |  |
| FORMAT | 3% | 0% | 0% | +3 |  |
| CAPABILITY | 3% | 0% | 0% | +3 |  |
| BUDGET_EXHAUSTED | 1% | 11% | 0% | +1 |  |
| POLLING | 1% | 3% | 2% | -1 |  |
| STUCK_AT_PROMPT | 1% | 0% | 0% | +1 |  |
| INTEGRITY_SUSPECT | 0% | 1% | 0% | +0 |  |

## 2. 判官主因（Qwen 失败 72 条；两家一致 15 条 = 21%）

| 主因 | gpt-6-sol 判 | claude 判 | 两家一致 | 占 Qwen 失败（一致） | Seed 失败上两家一致 |
|---|---|---|---|---|---|
| INSUFFICIENT_VERIFICATION | 43 | 8 | 5 | 7% | 0 |
| SPEC_MISINTERPRETATION | 6 | 24 | 4 | 6% | 1 |
| CAPABILITY | 5 | 17 | 3 | 4% | 3 |
| PREMATURE_COMPLETION | 0 | 16 | 0 | 0% | 0 |
| GAVE_UP | 7 | 3 | 2 | 3% | 0 |
| ACKNOWLEDGED_BUT_IGNORED | 3 | 1 | 0 | 0% | 0 |
| TASK_UNDERSPECIFIED | 4 | 0 | 0 | 0% | 1 |
| CANNOT_JUDGE | 2 | 0 | 0 | 0% | 0 |
| LOOP | 1 | 1 | 1 | 1% | 0 |
| COMMAND_ERRORS | 0 | 1 | 0 | 0% | 0 |
| BUDGET_EXHAUSTED | 0 | 1 | 0 | 0% | 4 |
| STUCK_AT_PROMPT | 1 | 0 | 0 | 0% | 0 |

## 3. 代表轨迹（两家一致的主因）

- **INSUFFICIENT_VERIFICATION**：`constraints-scheduling__BqJuKpj`、`headless-terminal__iuFLcF2`、`query-optimize__9X6qLNx`、`query-optimize__ZK2fLP5`、`sqlite-with-gcov__CwNy5ns`
- **SPEC_MISINTERPRETATION**：`code-from-image__xf3g9b3`、`hf-model-inference__pWcm4iy`、`kv-store-grpc__PT2yxxT`、`kv-store-grpc__njZYTjZ`
- **CAPABILITY**：`merge-diff-arc-agi-task__9MRbLq5`、`merge-diff-arc-agi-task__VkfMkNw`、`prove-plus-comm__fCN6ani`
- **GAVE_UP**：`polyglot-c-py__xcXJVAN`、`vulnerable-secret__tF3P5sA`
- **LOOP**：`llm-inference-batching-scheduler__fV85wp8`

## 4. 宣布完成前最后 3 轮有没有运行或检查（只看“宣布完成但没过”的 trial）

| 模型 | 宣布完成但没过 | 其中最后 3 轮有运行 / 检查 | 用掉的时限（中位数） |
|---|---|---|---|
| Qwen3-Coder-30B-A3B | 62 | 52 (84%) | 12% |
| Seed lite | 15 | 15 (100%) | 23% |
| gpt-6-sol | 3 | 3 (100%) | 7% |

## 5. 失败分布：Qwen 3 次全挂的题 17 道

chess-best-move、cobol-modernization、code-from-image、gcode-to-text、kv-store-grpc、large-scale-text-editing、llm-inference-batching-scheduler、merge-diff-arc-agi-task、mteb-retrieve、overfull-hbox、path-tracing-reverse、polyglot-c-py、query-optimize、regex-log、sqlite-db-truncate、tune-mjcf、vulnerable-secret
