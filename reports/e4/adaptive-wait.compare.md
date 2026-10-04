# e4-adaptive-wait vs e4-baseline-rerun（配对，26 题）

- Δ通过率（题级平均）：**-2.6 pp**，bootstrap 95% 区间 [-14.1, +9.0]
- 题级翻转：A过B不过 1，A不过B过 1；McNemar p = 1.000
- trial 级通过率：61.5% → 59.0%；超时 10 → 12（n 78 → 78）
- 平均轮数 14.4 → 13.7（-0.6）· 墙钟 456 → 498 s
- 输入 token/trial 227,588 → 201,819（-25,769）· 输出 20,286 → 18,176 · 缓存命中 29.1% → 14.4%
- 成本/trial 0.184 → 0.187（+0.003）

- fork 统计（B 合计）：auditor_calls=0, auditor_rejections=0, first_turn_rejections=0, stuck_reminders=0, adaptive_n=1610, adaptive_sentinel_finished=1111, adaptive_sentinel_timeout=31, adaptive_prompt_detected=69, adaptive_waited_sec_total=6821.1

## 失败标签占失败 trial 的比例（A → B）

- PREMATURE_COMPLETION: 66.7% → 65.6%
- BUDGET_EXHAUSTED: 33.3% → 34.4%
- TRUNCATED_READ: 33.3% → 15.6%
- COMMAND_NOT_FOUND: 16.7% → 21.9%
- POLLING: 13.3% → 6.2%
- STUCK_AT_PROMPT: 3.3% → 0.0%

## 逐题（A 通过率 → B 通过率）

| 题 | A | B | 变化 |
|---|---|---|---|
| count-dataset-tokens | 1.00 | 0.33 | ↓ |
| largest-eigenval | 1.00 | 0.33 | ↓ |
| cancel-async-tasks | 0.67 | 0.33 | ↓ |
| chess-best-move | 0.67 | 0.33 | ↓ |
| dna-insert | 0.33 | 0.00 | ↓ |
| mteb-retrieve | 0.67 | 0.33 | ↓ |
| adaptive-rejection-sampler | 0.33 | 0.33 | = |
| cobol-modernization | 1.00 | 1.00 | = |
| configure-git-webserver | 0.67 | 0.67 | = |
| fix-git | 1.00 | 1.00 | = |
| gcode-to-text | 0.00 | 0.00 | = |
| headless-terminal | 1.00 | 1.00 | = |
| nginx-request-logging | 1.00 | 1.00 | = |
| path-tracing-reverse | 0.00 | 0.00 | = |
| query-optimize | 0.00 | 0.00 | = |
| raman-fitting | 0.00 | 0.00 | = |
| regex-log | 1.00 | 1.00 | = |
| sanitize-git-repo | 0.33 | 0.33 | = |
| sqlite-db-truncate | 1.00 | 1.00 | = |
| sqlite-with-gcov | 0.67 | 0.67 | = |
| vulnerable-secret | 1.00 | 1.00 | = |
| kv-store-grpc | 0.67 | 1.00 | ↑ |
| llm-inference-batching-scheduler | 0.67 | 1.00 | ↑ |
| overfull-hbox | 0.67 | 1.00 | ↑ |
| pytorch-model-cli | 0.67 | 1.00 | ↑ |
| extract-elf | 0.00 | 0.67 | ↑ |
