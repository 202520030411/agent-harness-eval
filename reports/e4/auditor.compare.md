# e4-auditor vs e4-baseline-rerun（配对，26 题）

- Δ通过率（题级平均）：**+0.0 pp**，bootstrap 95% 区间 [-11.5, +10.3]
- 题级翻转：A过B不过 2，A不过B过 2；McNemar p = 1.000
- trial 级通过率：61.5% → 61.5%；超时 10 → 17（n 78 → 78）
- 平均轮数 14.4 → 16.4（+2.0）· 墙钟 456 → 588 s
- 输入 token/trial 227,588 → 316,088（+88,500）· 输出 20,286 → 20,251 · 缓存命中 29.1% → 27.8%
- 成本/trial 0.184 → 0.237（+0.054）

- fork 统计（B 合计）：auditor_calls=89, auditor_rejections=22, first_turn_rejections=0, stuck_reminders=0, adaptive_n=0, adaptive_sentinel_finished=0, adaptive_sentinel_timeout=0, adaptive_prompt_detected=0, adaptive_waited_sec_total=0

## 失败标签占失败 trial 的比例（A → B）

- PREMATURE_COMPLETION: 66.7% → 56.7%
- BUDGET_EXHAUSTED: 33.3% → 43.3%
- TRUNCATED_READ: 33.3% → 26.7%
- COMMAND_NOT_FOUND: 16.7% → 16.7%
- POLLING: 13.3% → 20.0%
- STUCK_AT_PROMPT: 3.3% → 3.3%

## 逐题（A 通过率 → B 通过率）

| 题 | A | B | 变化 |
|---|---|---|---|
| cancel-async-tasks | 0.67 | 0.00 | ↓ |
| count-dataset-tokens | 1.00 | 0.67 | ↓ |
| largest-eigenval | 1.00 | 0.67 | ↓ |
| chess-best-move | 0.67 | 0.33 | ↓ |
| configure-git-webserver | 0.67 | 0.33 | ↓ |
| mteb-retrieve | 0.67 | 0.33 | ↓ |
| sanitize-git-repo | 0.33 | 0.00 | ↓ |
| cobol-modernization | 1.00 | 1.00 | = |
| fix-git | 1.00 | 1.00 | = |
| gcode-to-text | 0.00 | 0.00 | = |
| headless-terminal | 1.00 | 1.00 | = |
| nginx-request-logging | 1.00 | 1.00 | = |
| path-tracing-reverse | 0.00 | 0.00 | = |
| raman-fitting | 0.00 | 0.00 | = |
| regex-log | 1.00 | 1.00 | = |
| sqlite-db-truncate | 1.00 | 1.00 | = |
| sqlite-with-gcov | 0.67 | 0.67 | = |
| vulnerable-secret | 1.00 | 1.00 | = |
| adaptive-rejection-sampler | 0.33 | 0.67 | ↑ |
| dna-insert | 0.33 | 0.67 | ↑ |
| extract-elf | 0.00 | 0.33 | ↑ |
| query-optimize | 0.00 | 0.33 | ↑ |
| kv-store-grpc | 0.67 | 1.00 | ↑ |
| llm-inference-batching-scheduler | 0.67 | 1.00 | ↑ |
| overfull-hbox | 0.67 | 1.00 | ↑ |
| pytorch-model-cli | 0.67 | 1.00 | ↑ |
