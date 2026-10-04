# e4s-contract vs e4s-baseline（配对，25 题）

- Δ通过率（题级平均）：**+0.0 pp**，bootstrap 95% 区间 [-12.0, +12.0]
- 题级翻转：A过B不过 2，A不过B过 1；McNemar p = 1.000
- trial 级通过率：88.0% → 87.0%；超时 0 → 0（n 50 → 46）
- 平均轮数 11.6 → 13.2（+1.7）· 墙钟 113 → 162 s
- 输入 token/trial 138,475 → 232,059（+93,584）· 输出 4,468 → 6,797 · 缓存命中 90.8% → 91.7%
- 成本/trial 0.101 → 0.159（+0.057）

- fork 统计（B 合计）：auditor_calls=0, auditor_rejections=0, first_turn_rejections=16, stuck_reminders=0, adaptive_n=0, adaptive_sentinel_finished=0, adaptive_sentinel_timeout=0, adaptive_prompt_detected=0, adaptive_waited_sec_total=0

## 失败标签占失败 trial 的比例（A → B）

- PREMATURE_COMPLETION: 100.0% → 100.0%
- COMMAND_NOT_FOUND: 16.7% → 16.7%
- POLLING: 16.7% → 0.0%

## 逐题（A 通过率 → B 通过率）

| 题 | A | B | 变化 |
|---|---|---|---|
| gcode-to-text | 1.00 | 0.00 | ↓ |
| mteb-retrieve | 1.00 | 0.50 | ↓ |
| raman-fitting | 0.50 | 0.00 | ↓ |
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
| nginx-request-logging | 1.00 | 1.00 | = |
| overfull-hbox | 1.00 | 1.00 | = |
| path-tracing-reverse | 1.00 | 1.00 | = |
| pytorch-model-cli | 1.00 | 1.00 | = |
| regex-log | 1.00 | 1.00 | = |
| sanitize-git-repo | 1.00 | 1.00 | = |
| sqlite-db-truncate | 1.00 | 1.00 | = |
| sqlite-with-gcov | 1.00 | 1.00 | = |
| dna-insert | 0.50 | 1.00 | ↑ |
| extract-elf | 0.00 | 0.50 | ↑ |
| kv-store-grpc | 0.50 | 1.00 | ↑ |
| query-optimize | 0.50 | 1.00 | ↑ |
