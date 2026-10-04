# e1-baseline-seed

- trials: 123（41 题）; status: {'agent_timeout': 16, 'ok': 107}
- 环境成功 100.0% · agent 安装成功 100.0% · reward-only 通过 68.3% · 端到端通过 68.3%
- mean（trial 级）68.3% · pass@k（题级）82.9%
- 平均轮数 13.6 · 平均墙钟 378 s · 每 trial 成本 0.155（配置单位）· 总成本 19.11
- 输入 token 25,781,061 · 输出 1,954,215 · 缓存命中 32.9%
- 空等待轮 60 · 解析错误轮 6 · 截断观察 54 · 压缩 0

## 失败标签（39 条失败 trial，可多标签）

- PREMATURE_COMPLETION: 25（64.1%）
- BUDGET_EXHAUSTED: 14（35.9%）
- TRUNCATED_READ: 11（28.2%）
- COMMAND_NOT_FOUND: 9（23.1%）
- POLLING: 3（7.7%）
- STUCK_AT_PROMPT: 1（2.6%）

## 题级

| 题 | mean | pass@k |
|---|---|---|
| adaptive-rejection-sampler | 0.33 | 1 |
| build-pmars | 1.00 | 1 |
| cancel-async-tasks | 0.00 | 0 |
| chess-best-move | 0.00 | 0 |
| cobol-modernization | 0.67 | 1 |
| code-from-image | 1.00 | 1 |
| configure-git-webserver | 0.67 | 1 |
| constraints-scheduling | 1.00 | 1 |
| count-dataset-tokens | 0.67 | 1 |
| dna-insert | 0.33 | 1 |
| extract-elf | 0.00 | 0 |
| fix-code-vulnerability | 1.00 | 1 |
| fix-git | 1.00 | 1 |
| gcode-to-text | 0.00 | 0 |
| git-leak-recovery | 1.00 | 1 |
| git-multibranch | 1.00 | 1 |
| headless-terminal | 0.67 | 1 |
| hf-model-inference | 1.00 | 1 |
| kv-store-grpc | 0.67 | 1 |
| large-scale-text-editing | 1.00 | 1 |
| largest-eigenval | 0.33 | 1 |
| llm-inference-batching-scheduler | 0.67 | 1 |
| log-summary-date-ranges | 1.00 | 1 |
| merge-diff-arc-agi-task | 1.00 | 1 |
| mteb-retrieve | 0.67 | 1 |
| nginx-request-logging | 1.00 | 1 |
| openssl-selfsigned-cert | 1.00 | 1 |
| overfull-hbox | 0.33 | 1 |
| path-tracing-reverse | 0.00 | 0 |
| polyglot-c-py | 1.00 | 1 |
| prove-plus-comm | 1.00 | 1 |
| pypi-server | 1.00 | 1 |
| pytorch-model-cli | 0.67 | 1 |
| query-optimize | 0.00 | 0 |
| raman-fitting | 0.00 | 0 |
| regex-log | 1.00 | 1 |
| sanitize-git-repo | 0.67 | 1 |
| sqlite-db-truncate | 1.00 | 1 |
| sqlite-with-gcov | 0.67 | 1 |
| tune-mjcf | 1.00 | 1 |
| vulnerable-secret | 1.00 | 1 |
