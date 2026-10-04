# e2-baseline-strong

- trials: 41（41 题）; status: {'ok': 40, 'agent_error': 1}
- 环境成功 100.0% · agent 安装成功 100.0% · reward-only 通过 95.0% · 端到端通过 92.7%
- mean（trial 级）95.0% · pass@k（题级）95.0%
- 平均轮数 10.7 · 平均墙钟 91 s · 每 trial 成本 0.086（配置单位）· 总成本 3.45
- 输入 token 4,442,228 · 输出 158,414 · 缓存命中 90.3%
- 空等待轮 59 · 解析错误轮 0 · 截断观察 18 · 压缩 0


## 失败标签（2 条失败 trial，可多标签）

- PREMATURE_COMPLETION: 2（100.0%）
- TRUNCATED_READ: 1（50.0%）

## 题级

| 题 | mean | pass@k |
|---|---|---|
| adaptive-rejection-sampler | 1.00 | 1 |
| build-pmars | 1.00 | 1 |
| cancel-async-tasks | 1.00 | 1 |
| chess-best-move | 1.00 | 1 |
| cobol-modernization | 1.00 | 1 |
| code-from-image | 1.00 | 1 |
| configure-git-webserver | 1.00 | 1 |
| constraints-scheduling | 1.00 | 1 |
| count-dataset-tokens | 1.00 | 1 |
| dna-insert | 1.00 | 1 |
| extract-elf | 1.00 | 1 |
| fix-code-vulnerability | 1.00 | 1 |
| fix-git | 1.00 | 1 |
| gcode-to-text | 0.00 | 0 |
| git-leak-recovery | 1.00 | 1 |
| git-multibranch | 1.00 | 1 |
| headless-terminal | 1.00 | 1 |
| hf-model-inference | 1.00 | 1 |
| kv-store-grpc | 1.00 | 1 |
| large-scale-text-editing | 1.00 | 1 |
| largest-eigenval | 1.00 | 1 |
| llm-inference-batching-scheduler | 1.00 | 1 |
| log-summary-date-ranges | 1.00 | 1 |
| merge-diff-arc-agi-task | 1.00 | 1 |
| mteb-retrieve | 1.00 | 1 |
| nginx-request-logging | 1.00 | 1 |
| openssl-selfsigned-cert | 1.00 | 1 |
| overfull-hbox | 1.00 | 1 |
| path-tracing-reverse | 1.00 | 1 |
| polyglot-c-py | 1.00 | 1 |
| prove-plus-comm | 1.00 | 1 |
| pypi-server | 1.00 | 1 |
| pytorch-model-cli | 1.00 | 1 |
| query-optimize | 1.00 | 1 |
| raman-fitting | 0.00 | 0 |
| regex-log | 1.00 | 1 |
| sanitize-git-repo | 1.00 | 1 |
| sqlite-db-truncate | 1.00 | 1 |
| sqlite-with-gcov | 1.00 | 1 |
| tune-mjcf | 1.00 | 1 |
