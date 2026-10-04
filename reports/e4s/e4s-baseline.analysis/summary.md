# e4s-baseline

- trials: 52（26 题）; status: {'ok': 50, 'agent_error': 2}
- 环境成功 100.0% · agent 安装成功 100.0% · reward-only 通过 88.0% · 端到端通过 84.6%
- mean（trial 级）88.0% · pass@k（题级）96.0%
- 平均轮数 11.6 · 平均墙钟 113 s · 每 trial 成本 0.101（配置单位）· 总成本 5.06
- 输入 token 6,923,731 · 输出 223,375 · 缓存命中 90.8%
- 空等待轮 89 · 解析错误轮 0 · 截断观察 25 · 压缩 0
- fork stats total: {'first_turn_rejections': 0, 'stuck_reminders': 0, 'auditor_calls': 0, 'auditor_rejections': 0, 'adaptive_n': 0, 'adaptive_sentinel_finished': 0, 'adaptive_sentinel_timeout': 0, 'adaptive_prompt_detected': 0, 'adaptive_waited_sec_total': 0}

## 失败标签（6 条失败 trial，可多标签）

- PREMATURE_COMPLETION: 6（100.0%）
- POLLING: 1（16.7%）
- COMMAND_NOT_FOUND: 1（16.7%）

## 题级

| 题 | mean | pass@k |
|---|---|---|
| adaptive-rejection-sampler | 1.00 | 1 |
| cancel-async-tasks | 1.00 | 1 |
| chess-best-move | 1.00 | 1 |
| cobol-modernization | 1.00 | 1 |
| configure-git-webserver | 1.00 | 1 |
| count-dataset-tokens | 1.00 | 1 |
| dna-insert | 0.50 | 1 |
| extract-elf | 0.00 | 0 |
| fix-git | 1.00 | 1 |
| gcode-to-text | 1.00 | 1 |
| headless-terminal | 1.00 | 1 |
| kv-store-grpc | 0.50 | 1 |
| largest-eigenval | 1.00 | 1 |
| llm-inference-batching-scheduler | 1.00 | 1 |
| mteb-retrieve | 1.00 | 1 |
| nginx-request-logging | 1.00 | 1 |
| overfull-hbox | 1.00 | 1 |
| path-tracing-reverse | 1.00 | 1 |
| pytorch-model-cli | 1.00 | 1 |
| query-optimize | 0.50 | 1 |
| raman-fitting | 0.50 | 1 |
| regex-log | 1.00 | 1 |
| sanitize-git-repo | 1.00 | 1 |
| sqlite-db-truncate | 1.00 | 1 |
| sqlite-with-gcov | 1.00 | 1 |
