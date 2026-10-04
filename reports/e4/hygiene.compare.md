# e4-hygiene vs e4-baseline-rerun（配对，26 题）

- Δ通过率（题级平均）：**-1.3 pp**，bootstrap 95% 区间 [-12.8, +10.3]
- 题级翻转：A过B不过 2，A不过B过 1；McNemar p = 1.000
- trial 级通过率：61.5% → 60.3%；超时 10 → 12（n 78 → 78）
- 平均轮数 14.4 → 14.0（-0.4）· 墙钟 456 → 485 s
- 输入 token/trial 227,588 → 187,815（-39,773）· 输出 20,286 → 19,768 · 缓存命中 29.1% → 19.1%
- 成本/trial 0.184 → 0.175（-0.009）

- fork 统计（B 合计）：auditor_calls=0, auditor_rejections=0, first_turn_rejections=0, stuck_reminders=0, adaptive_n=0, adaptive_sentinel_finished=0, adaptive_sentinel_timeout=0, adaptive_prompt_detected=0, adaptive_waited_sec_total=0

## 失败标签占失败 trial 的比例（A → B）

- PREMATURE_COMPLETION: 66.7% → 64.5%
- BUDGET_EXHAUSTED: 33.3% → 35.5%
- TRUNCATED_READ: 33.3% → 25.8%
- COMMAND_NOT_FOUND: 16.7% → 16.1%
- POLLING: 13.3% → 9.7%
- STUCK_AT_PROMPT: 3.3% → 0.0%

## 逐题（A 通过率 → B 通过率）

| 题 | A | B | 变化 |
|---|---|---|---|
| largest-eigenval | 1.00 | 0.33 | ↓ |
| chess-best-move | 0.67 | 0.00 | ↓ |
| configure-git-webserver | 0.67 | 0.33 | ↓ |
| dna-insert | 0.33 | 0.00 | ↓ |
| mteb-retrieve | 0.67 | 0.33 | ↓ |
| cancel-async-tasks | 0.67 | 0.67 | = |
| cobol-modernization | 1.00 | 1.00 | = |
| count-dataset-tokens | 1.00 | 1.00 | = |
| fix-git | 1.00 | 1.00 | = |
| gcode-to-text | 0.00 | 0.00 | = |
| headless-terminal | 1.00 | 1.00 | = |
| llm-inference-batching-scheduler | 0.67 | 0.67 | = |
| nginx-request-logging | 1.00 | 1.00 | = |
| overfull-hbox | 0.67 | 0.67 | = |
| path-tracing-reverse | 0.00 | 0.00 | = |
| query-optimize | 0.00 | 0.00 | = |
| raman-fitting | 0.00 | 0.00 | = |
| regex-log | 1.00 | 1.00 | = |
| sanitize-git-repo | 0.33 | 0.33 | = |
| sqlite-db-truncate | 1.00 | 1.00 | = |
| vulnerable-secret | 1.00 | 1.00 | = |
| adaptive-rejection-sampler | 0.33 | 0.67 | ↑ |
| kv-store-grpc | 0.67 | 1.00 | ↑ |
| pytorch-model-cli | 0.67 | 1.00 | ↑ |
| sqlite-with-gcov | 0.67 | 1.00 | ↑ |
| extract-elf | 0.00 | 0.67 | ↑ |
