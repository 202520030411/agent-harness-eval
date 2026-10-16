# 反思

题目难度（每题 3 次左右）：{'never_solved': 56, 'mixed_outcome': 13, 'always_solved': 5, 'n_tasks': 74}

## harness 队列
- **宣布完成但判分失败（PREMATURE_COMPLETION）**（premature_completion）：140/189，占失败 74%；先验 MIXED；试过：['E4-contract', 'E4-selfcheck', 'E4-auditor', 'E4v2-gradercheck', 'E4p-contract-v1', 'E4p-contract-v2', 'H17-conditional', 'E4s-contract', 'E4s-selfcheck', 'QARM-H2-vs-H1', 'QEVAL-2x2']
- **用 echo 打印“完成”代替真正的检查**（echo_theater）：82/189，占失败 43%；先验 HARNESS；试过：['QARM-H2-vs-H1', 'QEVAL-2x2']
- **读类命令的输出被截断（TRUNCATED_READ）**（truncated_read）：76/189，占失败 40%；先验 MIXED；试过：['E4-adaptive-wait', 'SWEV-adaptive-wait']
- **逐行追加写文件（≥10 轮 echo/printf >>）**（line_by_line_write）：59/222，占失败 31%；先验 MIXED；试过：无
- **没宣布完成就用完预算（BUDGET_EXHAUSTED）**（budget_exhausted）：48/189，占失败 25%；先验 MIXED；试过：['E4-adaptive-wait', 'SWEV-adaptive-wait', 'E4v2-checkpoint']
- **跑满轮数上限**（turn_cap）：42/222，占失败 22%；先验 MIXED；试过：['E4v2-checkpoint', 'QARM-H1', 'QEVAL-2x2']
- **出现过格式错误（回复不是 harness 要的 JSON）**（format_error）：42/222，占失败 21%；先验 HARNESS；试过：['QARM-H1', 'QEVAL-2x2']
- **宣布完成前最后一次改文件后没运行过任何东西**（claim_without_run）：19/222，占失败 10%；先验 MIXED；试过：['E4-selfcheck', 'E4-auditor', 'E4v2-gradercheck', 'E4s-selfcheck', 'QARM-H2-vs-H1', 'QEVAL-2x2']

## 训练队列（模型侧）
- 明知没做成仍宣布完成：占失败 12%

## 人工队列
- 用了环境里没有的命令：attribution unknown: needs a cross-harness or cross-model comparison
- 每次都做不出来的题：task defect or capability gap: audit a sample with the 'only edit the instruction' test before using them
