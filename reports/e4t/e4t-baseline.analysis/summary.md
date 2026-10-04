# e4t-baseline

- trials: 42（14 题）; status: {'agent_timeout': 8, 'ok': 33, 'setup_failed': 1}
- 环境成功 97.6% · agent 安装成功 100.0% · reward-only 通过 65.9% · 端到端通过 64.3%
- mean（trial 级）65.9% · pass@k（题级）85.7%
- 平均轮数 16.0 · 平均墙钟 400 s · 每 trial 成本 0.177（配置单位）· 总成本 7.26
- 输入 token 9,499,381 · 输出 658,769 · 缓存命中 27.9%
- 空等待轮 32 · 解析错误轮 1 · 截断观察 30 · 压缩 0
- fork stats total: {'first_turn_rejections': 0, 'stuck_reminders': 0, 'auditor_calls': 0, 'auditor_rejections': 0, 'adaptive_n': 0, 'adaptive_sentinel_finished': 0, 'adaptive_sentinel_timeout': 0, 'adaptive_prompt_detected': 0, 'adaptive_waited_sec_total': 0}

## 失败标签（14 条失败 trial，可多标签）

- PREMATURE_COMPLETION: 9（64.3%）
- BUDGET_EXHAUSTED: 5（35.7%）
- TRUNCATED_READ: 4（28.6%）
- COMMAND_NOT_FOUND: 3（21.4%）
- POLLING: 2（14.3%）

## 题级

| 题 | mean | pass@k |
|---|---|---|
| adaptive-rejection-sampler | 0.67 | 1 |
| build-pmars | 1.00 | 1 |
| cancel-async-tasks | 0.33 | 1 |
| chess-best-move | 0.33 | 1 |
| count-dataset-tokens | 1.00 | 1 |
| dna-insert | 0.50 | 1 |
| extract-elf | 0.00 | 0 |
| fix-code-vulnerability | 1.00 | 1 |
| fix-git | 1.00 | 1 |
| headless-terminal | 1.00 | 1 |
| pytorch-model-cli | 1.00 | 1 |
| raman-fitting | 0.00 | 0 |
| sanitize-git-repo | 0.33 | 1 |
| vulnerable-secret | 1.00 | 1 |
