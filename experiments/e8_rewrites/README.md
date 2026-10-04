# E8 — 改题重跑（TASK_UNDERSPECIFIED 是不是真的"题的锅"）

选题依据：E1 判官把这些题的失败主因判为 SPEC_MISINTERPRETATION / TASK_UNDERSPECIFIED，且 clarity 评分 intent/target ≥ 2（`reports/clarity.jsonl`）。
改写原则：**只补接口约定，不给解法**——补的都是判官在 `Underspecification:` 里指出来的缺口（单位、地址约定、插入边界、取消语义、"best"的定义），
每条都能在题目自带的隐藏测试里找到依据；不提示算法、不给期望数值。

| 题 | 补了什么 | 依据 |
|---|---|---|
| raman-fitting | 数据文件名/格式、Lorentzian 形式、gamma=HWHM、x0 单位 cm^-1 及石墨烯 G/2D 大致位置 | test 里的期望值与容差 |
| extract-elf | 取哪些段、4 字节小端、地址=sh_addr 不加 PIE 偏移、要在另一个 gcc 编的二进制上也能用 | test 里的参考实现 REF |
| dna-insert | 只需 1 对引物、插入边界不平移、引物拼接关系、只含 ACGT、4 行 | test_primers 的断言 |
| cancel-async-tasks | 取消语义：已启动的取消、排队的不启动、等 finally 跑完；gather 的坑 | test_tasks_cancel_* |
| chess-best-move | "best"=一步将死、可能多解、位置只在图里、建议用 python-chess 验证 | test_move_correct |
| path-tracing-reverse | **不改**，作为对照（E1 三次失败全是 BUDGET_EXHAUSTED，题面清楚） | — |

对照组：E1 + E4 baseline-rerun 里同样 6 题各 3 次（共 6 次/题）。
预期（HYPOTHESES H8）：改题后 5 道题的通过率上升 ≥ 2 题，对照题不变；若改题也不涨 → 判官的 "TASK_UNDERSPECIFIED" 至少对这些题是错的（该记为 CAPABILITY）。
