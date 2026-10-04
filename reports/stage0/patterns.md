# 阶段 0：三种毛病的规则统计（TB 2.1 干净题，同一口径）

| 指标 | Qwen3-Coder-30B-A3B | Seed lite | gpt-6-sol |
|---|---|---|---|
| 出现过 JSON 控制字符错误（全部 trial） | 45/90 (50%) | 1/180 (1%) | 0/64 (0%) |
| 最后 3 步全是解析错误、卡死到结束（全部 trial） | 3/90 (3%) | 0/180 (0%) | 0/64 (0%) |
| 明知没做成仍宣布完成（失败 trial） | 19/72 (26%) | 1/34 (3%) | 1/6 (17%) |
| 用 echo 打印代替检查（全部 trial） | 48/90 (53%) | 3/180 (2%) | 1/64 (2%) |
| 用 echo 打印代替检查（失败 trial） | 37/72 (51%) | 0/34 (0%) | 0/6 (0%) |
| 平均解析错误轮数 / trial | 4.9 | 0.1 | 0.0 |
| 通过率 | 18/90 (20%) | 146/180 (81%) | 58/64 (91%) |

## Qwen 的例子

- json_loop_end：`large-scale-text-editing__yXg9FYv`、`merge-diff-arc-agi-task__9MRbLq5`、`prove-plus-comm__fCN6ani`
- false_success：`chess-best-move__rnTB9No`、`code-from-image__8KpgdFK`、`large-scale-text-editing__auoeCxp`、`llm-inference-batching-scheduler__YYVBAwn`、`log-summary-date-ranges__hF75zLt`、`merge-diff-arc-agi-task__dJ7kFv6`
- echo_theater：`adaptive-rejection-sampler__cH2LjKg`、`adaptive-rejection-sampler__hT8Fnsa`、`chess-best-move__rnTB9No`、`cobol-modernization__CEKufKx`、`fix-git__rU2nJCn`、`git-leak-recovery__w9aY3CY`
