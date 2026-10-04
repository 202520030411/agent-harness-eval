# e4s-selfcheck

- trials: 52（26 题）; status: {'ok': 44, 'setup_failed': 5, 'agent_timeout': 1, 'agent_error': 2}
- 环境成功 90.4% · agent 安装成功 100.0% · reward-only 通过 86.7% · 端到端通过 75.0%
- mean（trial 级）86.7% · pass@k（题级）91.7%
- 平均轮数 20.5 · 平均墙钟 203 s · 每 trial 成本 0.181（配置单位）· 总成本 8.13
- 输入 token 14,726,995 · 输出 351,427 · 缓存命中 95.0%
- 空等待轮 111 · 解析错误轮 0 · 截断观察 28 · 压缩 0
- fork stats total: {'first_turn_rejections': 0, 'stuck_reminders': 0, 'auditor_calls': 0, 'auditor_rejections': 0, 'adaptive_n': 0, 'adaptive_sentinel_finished': 0, 'adaptive_sentinel_timeout': 0, 'adaptive_prompt_detected': 0, 'adaptive_waited_sec_total': 0}

## 失败标签（6 条失败 trial，可多标签）

- PREMATURE_COMPLETION: 5（83.3%）
- INTEGRITY_SUSPECT: 1（16.7%）
- BUDGET_EXHAUSTED: 1（16.7%）
- POLLING: 1（16.7%）

## 题级

| 题 | mean | pass@k |
|---|---|---|
| adaptive-rejection-sampler | 1.00 | 1 |
| cancel-async-tasks | 1.00 | 1 |
| chess-best-move | 1.00 | 1 |
| cobol-modernization | 1.00 | 1 |
| configure-git-webserver | 1.00 | 1 |
| count-dataset-tokens | 1.00 | 1 |
| dna-insert | 0.00 | 0 |
| extract-elf | 0.50 | 1 |
| fix-git | 1.00 | 1 |
| gcode-to-text | 0.50 | 1 |
| headless-terminal | 1.00 | 1 |
| kv-store-grpc | 1.00 | 1 |
| largest-eigenval | 1.00 | 1 |
| llm-inference-batching-scheduler | 1.00 | 1 |
| mteb-retrieve | 1.00 | 1 |
| nginx-request-logging | 1.00 | 1 |
| overfull-hbox | 1.00 | 1 |
| path-tracing-reverse | 1.00 | 1 |
| pytorch-model-cli | 1.00 | 1 |
| query-optimize | 1.00 | 1 |
| raman-fitting | 0.00 | 0 |
| regex-log | 1.00 | 1 |
| sanitize-git-repo | 0.50 | 1 |
| sqlite-db-truncate | 1.00 | 1 |
