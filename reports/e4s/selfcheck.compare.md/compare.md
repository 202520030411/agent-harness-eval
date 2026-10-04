# e4s-selfcheck vs e4s-baseline（配对，24 题）

- Δ通过率（题级平均）：**-2.1 pp**，bootstrap 95% 区间 [-12.5, +8.3]
- 题级翻转：A过B不过 2，A不过B过 1；McNemar p = 1.000
- trial 级通过率：88.0% → 86.7%；超时 0 → 1（n 50 → 45）
- 平均轮数 11.6 → 20.5（+9.0）· 墙钟 113 → 203 s
- 输入 token/trial 138,475 → 327,267（+188,792）· 输出 4,468 → 7,809 · 缓存命中 90.8% → 95.0%
- 成本/trial 0.101 → 0.181（+0.079）

- fork 统计（B 合计）：auditor_calls=0, auditor_rejections=0, first_turn_rejections=0, stuck_reminders=0, adaptive_n=0, adaptive_sentinel_finished=0, adaptive_sentinel_timeout=0, adaptive_prompt_detected=0, adaptive_waited_sec_total=0

## 失败标签占失败 trial 的比例（A → B）

- PREMATURE_COMPLETION: 100.0% → 83.3%
- BUDGET_EXHAUSTED: 0.0% → 16.7%
- COMMAND_NOT_FOUND: 16.7% → 0.0%
- POLLING: 16.7% → 16.7%

## 逐题（A 通过率 → B 通过率）

| 题 | A | B | 变化 |
|---|---|---|---|
| dna-insert | 0.50 | 0.00 | ↓ |
| gcode-to-text | 1.00 | 0.50 | ↓ |
| raman-fitting | 0.50 | 0.00 | ↓ |
| sanitize-git-repo | 1.00 | 0.50 | ↓ |
| adaptive-rejection-sampler | 1.00 | 1.00 | = |
| cancel-async-tasks | 1.00 | 1.00 | = |
| chess-best-move | 1.00 | 1.00 | = |
| cobol-modernization | 1.00 | 1.00 | = |
| configure-git-webserver | 1.00 | 1.00 | = |
| count-dataset-tokens | 1.00 | 1.00 | = |
| fix-git | 1.00 | 1.00 | = |
| headless-terminal | 1.00 | 1.00 | = |
| largest-eigenval | 1.00 | 1.00 | = |
| llm-inference-batching-scheduler | 1.00 | 1.00 | = |
| mteb-retrieve | 1.00 | 1.00 | = |
| nginx-request-logging | 1.00 | 1.00 | = |
| overfull-hbox | 1.00 | 1.00 | = |
| path-tracing-reverse | 1.00 | 1.00 | = |
| pytorch-model-cli | 1.00 | 1.00 | = |
| regex-log | 1.00 | 1.00 | = |
| sqlite-db-truncate | 1.00 | 1.00 | = |
| extract-elf | 0.00 | 0.50 | ↑ |
| kv-store-grpc | 0.50 | 1.00 | ↑ |
| query-optimize | 0.50 | 1.00 | ↑ |
