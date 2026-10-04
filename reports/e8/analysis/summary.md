# e8-rewrite-seed

- trials: 18（6 题）; status: {'ok': 12, 'agent_timeout': 6}
- 环境成功 100.0% · agent 安装成功 100.0% · reward-only 通过 44.4% · 端到端通过 44.4%
- mean（trial 级）44.4% · pass@k（题级）50.0%
- 平均轮数 15 · 平均墙钟 726 s · 每 trial 成本 0.345（配置单位）· 总成本 6.2
- 输入 token 6,344,804 · 输出 567,682 · 缓存命中 8.0%
- 空等待轮 0 · 解析错误轮 2 · 截断观察 15 · 压缩 0


## 失败标签（10 条失败 trial，可多标签）

- BUDGET_EXHAUSTED: 6（60.0%）
- TRUNCATED_READ: 4（40.0%）
- PREMATURE_COMPLETION: 4（40.0%）
- COMMAND_NOT_FOUND: 1（10.0%）

## 题级

| 题 | mean | pass@k |
|---|---|---|
| cancel-async-tasks | 1.00 | 1 |
| chess-best-move | 0.67 | 1 |
| dna-insert | 0.00 | 0 |
| extract-elf | 1.00 | 1 |
| path-tracing-reverse | 0.00 | 0 |
| raman-fitting | 0.00 | 0 |
