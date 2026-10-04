# e4t-contract vs e4t-baseline（配对，14 题）

- Δ通过率（题级平均）：**+3.6 pp**，bootstrap 95% 区间 [-8.3, +20.2]
- 题级翻转：A过B不过 0，A不过B过 1；McNemar p = 1.000
- trial 级通过率：65.9% → 69.0%；超时 8 → 4（n 41 → 42）
- 平均轮数 16.0 → 12.8（-3.1）· 墙钟 400 → 367 s
- 输入 token/trial 231,692 → 152,275（-79,417）· 输出 16,068 → 14,966 · 缓存命中 27.9% → 25.5%
- 成本/trial 0.177 → 0.131（-0.046）

- fork 统计（B 合计）：auditor_calls=0, auditor_rejections=0, first_turn_rejections=30, stuck_reminders=0, adaptive_n=0, adaptive_sentinel_finished=0, adaptive_sentinel_timeout=0, adaptive_prompt_detected=0, adaptive_waited_sec_total=0

## 失败标签占失败 trial 的比例（A → B）

- PREMATURE_COMPLETION: 64.3% → 92.3%
- BUDGET_EXHAUSTED: 35.7% → 7.7%
- TRUNCATED_READ: 28.6% → 15.4%
- COMMAND_NOT_FOUND: 21.4% → 0.0%
- POLLING: 14.3% → 0.0%

## 逐题（A 通过率 → B 通过率）

| 题 | A | B | 变化 |
|---|---|---|---|
| build-pmars | 1.00 | 0.67 | ↓ |
| dna-insert | 0.50 | 0.33 | ↓ |
| adaptive-rejection-sampler | 0.67 | 0.67 | = |
| cancel-async-tasks | 0.33 | 0.33 | = |
| chess-best-move | 0.33 | 0.33 | = |
| count-dataset-tokens | 1.00 | 1.00 | = |
| fix-code-vulnerability | 1.00 | 1.00 | = |
| fix-git | 1.00 | 1.00 | = |
| headless-terminal | 1.00 | 1.00 | = |
| pytorch-model-cli | 1.00 | 1.00 | = |
| raman-fitting | 0.00 | 0.00 | = |
| sanitize-git-repo | 0.33 | 0.33 | = |
| vulnerable-secret | 1.00 | 1.00 | = |
| extract-elf | 0.00 | 1.00 | ↑ |
