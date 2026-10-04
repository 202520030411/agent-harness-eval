# e4-selfcheck vs e4-baseline-rerun（配对，26 题）

- Δ通过率（题级平均）：**+6.4 pp**，bootstrap 95% 区间 [-2.6, +15.4]
- 题级翻转：A过B不过 1，A不过B过 1；McNemar p = 1.000
- trial 级通过率：61.5% → 67.9%；超时 10 → 14（n 78 → 78）
- 平均轮数 14.4 → 16.8（+2.5）· 墙钟 456 → 489 s
- 输入 token/trial 227,588 → 323,390（+95,802）· 输出 20,286 → 20,832 · 缓存命中 29.1% → 25.6%
- 成本/trial 0.184 → 0.249（+0.065）

- fork 统计（B 合计）：auditor_calls=0, auditor_rejections=0, first_turn_rejections=0, stuck_reminders=0, adaptive_n=0, adaptive_sentinel_finished=0, adaptive_sentinel_timeout=0, adaptive_prompt_detected=0, adaptive_waited_sec_total=0

## 失败标签占失败 trial 的比例（A → B）

- PREMATURE_COMPLETION: 66.7% → 68.0%
- BUDGET_EXHAUSTED: 33.3% → 32.0%
- TRUNCATED_READ: 33.3% → 24.0%
- COMMAND_NOT_FOUND: 16.7% → 8.0%
- POLLING: 13.3% → 16.0%
- STUCK_AT_PROMPT: 3.3% → 0.0%

## 逐题（A 通过率 → B 通过率）

| 题 | A | B | 变化 |
|---|---|---|---|
| count-dataset-tokens | 1.00 | 0.67 | ↓ |
| cancel-async-tasks | 0.67 | 0.33 | ↓ |
| dna-insert | 0.33 | 0.00 | ↓ |
| mteb-retrieve | 0.67 | 0.33 | ↓ |
| cobol-modernization | 1.00 | 1.00 | = |
| configure-git-webserver | 0.67 | 0.67 | = |
| fix-git | 1.00 | 1.00 | = |
| gcode-to-text | 0.00 | 0.00 | = |
| headless-terminal | 1.00 | 1.00 | = |
| largest-eigenval | 1.00 | 1.00 | = |
| nginx-request-logging | 1.00 | 1.00 | = |
| overfull-hbox | 0.67 | 0.67 | = |
| path-tracing-reverse | 0.00 | 0.00 | = |
| query-optimize | 0.00 | 0.00 | = |
| raman-fitting | 0.00 | 0.00 | = |
| regex-log | 1.00 | 1.00 | = |
| sqlite-db-truncate | 1.00 | 1.00 | = |
| vulnerable-secret | 1.00 | 1.00 | = |
| extract-elf | 0.00 | 0.33 | ↑ |
| sanitize-git-repo | 0.33 | 0.67 | ↑ |
| chess-best-move | 0.67 | 1.00 | ↑ |
| kv-store-grpc | 0.67 | 1.00 | ↑ |
| llm-inference-batching-scheduler | 0.67 | 1.00 | ↑ |
| pytorch-model-cli | 0.67 | 1.00 | ↑ |
| sqlite-with-gcov | 0.67 | 1.00 | ↑ |
| adaptive-rejection-sampler | 0.33 | 1.00 | ↑ |
