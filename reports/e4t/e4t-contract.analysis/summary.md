# e4t-contract

- trials: 42（14 题）; status: {'agent_timeout': 4, 'ok': 38}
- 环境成功 100.0% · agent 安装成功 100.0% · reward-only 通过 69.0% · 端到端通过 69.0%
- mean（trial 级）69.0% · pass@k（题级）92.9%
- 平均轮数 12.8 · 平均墙钟 367 s · 每 trial 成本 0.131（配置单位）· 总成本 5.51
- 输入 token 6,395,554 · 输出 628,579 · 缓存命中 25.5%
- 空等待轮 10 · 解析错误轮 34 · 截断观察 21 · 压缩 0
- fork stats total: {'first_turn_rejections': 30, 'stuck_reminders': 0, 'auditor_calls': 0, 'auditor_rejections': 0, 'adaptive_n': 0, 'adaptive_sentinel_finished': 0, 'adaptive_sentinel_timeout': 0, 'adaptive_prompt_detected': 0, 'adaptive_waited_sec_total': 0}

## 失败标签（13 条失败 trial，可多标签）

- PREMATURE_COMPLETION: 12（92.3%）
- TRUNCATED_READ: 2（15.4%）
- BUDGET_EXHAUSTED: 1（7.7%）

## 题级

| 题 | mean | pass@k |
|---|---|---|
| adaptive-rejection-sampler | 0.67 | 1 |
| build-pmars | 0.67 | 1 |
| cancel-async-tasks | 0.33 | 1 |
| chess-best-move | 0.33 | 1 |
| count-dataset-tokens | 1.00 | 1 |
| dna-insert | 0.33 | 1 |
| extract-elf | 1.00 | 1 |
| fix-code-vulnerability | 1.00 | 1 |
| fix-git | 1.00 | 1 |
| headless-terminal | 1.00 | 1 |
| pytorch-model-cli | 1.00 | 1 |
| raman-fitting | 0.00 | 0 |
| sanitize-git-repo | 0.33 | 1 |
| vulnerable-secret | 1.00 | 1 |
