# 失败分类（v0，第 4 天人工标注后定稿）

顶层对齐 Terminal-Bench（ICLR 2026）论文的三大类：**Execution / Coherence / Verification**，另加两类非模型原因。每个标签标明：判定层（规则 / 判官）、信号定义、blame 候选。

## 1. 规则层标签（纯函数，硬判）

| 标签 | TB 类 | 信号（精确） | blame 候选 |
|---|---|---|---|
| `PREMATURE_COMPLETION` | Verification | 存在 `mark_task_complete` 且 reward==0 且无 ENVIRONMENT 标签 | MIXED |
| `BUDGET_EXHAUSTED` | Execution | 无 `mark_task_complete` 且 (`n_episodes` == max_turns 或 status==timeout) | MIXED |
| `POLLING` | Execution | ≥3 轮连续、每轮唯一 keystrokes 为空串 | HARNESS |
| `LOOP` | Execution | 三种变体（借 OpenHands `StuckDetector`，阈值可配）：(a) 同一 keystrokes 得到相同观察 ≥4 次；(b) 同一 keystrokes 得到相同错误 ≥3 次；(c) 两组 keystrokes A/B 交替 ≥6 个周期。记录变体名 | MIXED |
| `COMPACTION_LOOP` | Coherence | 发生 ≥2 次压缩，且两次压缩之间没有出现新的不同命令（借 OpenHands issue #8630 的"反复压缩不推进"） | HARNESS |
| `STUCK_AT_PROMPT` | Execution | 观察末尾匹配 `\[y/N\]|\(y/n\)|Password:|--More--|\(END\)|^> $`，且下一轮 keystrokes 不是对该提示的应答 | HARNESS |
| `PARSE_ERRORS` / `FORMAT` | Execution（harness 对齐） | 观察以 `Previous response had parsing errors` 开头的轮数；占比 >50% 升级为 `FORMAT` | MIXED |
| `COMMAND_NOT_FOUND` | Execution | 观察含 `command not found` / `No such file or directory` / `Permission denied` 的轮数 ≥2 | MODEL（计数用，不单独定失败） |
| `TRUNCATED_READ` | Execution | 读类命令（`cat`/`head`/`tail`/`sed -n`/`less`）后的观察含 `[... output limited to`；后两轮内出现写操作 → 置信度升高 | HARNESS |
| `COMPACTION_OCCURRED` | Coherence（候选） | `summarization_count>0` 或某 step `extra.context_management.type=="compaction"`；只是触发判官检查 `GOAL_DRIFT` | — |
| `HEREDOC_SUSPECT` | Execution | keystrokes 含 `<<` 且随后观察出现连续 `> ` 续行提示 | MIXED |
| `INTEGRITY_SUSPECT` | Verification | 通过与失败都查：keystrokes 触及 `/tests`、`/solution`、`/logs/verifier`、`reward.txt`、`/logs/agent`，或全盘 `grep -r /`、`/proc` 扫描、`yes` 灌盘（DSec 2609.22978 §6.4 的真实作弊/破坏清单；Harbor analyze 的 `reward_hacking`）。只是嫌疑，判官 Integrity 行定性 | MODEL |
| `PROVIDER_REFUSAL` | ENVIRONMENT | `agent_error` 且异常信息含 flagged / content policy / safety（如 OpenAI 拒答安全类题 vulnerable-secret，E2 2026-09-23） | ENVIRONMENT |
| `SETUP_FAILED` | ENVIRONMENT | `exception_info` 非空且发生在 agent_setup 前 | ENVIRONMENT |
| `AGENT_RUNTIME_ERROR` | ENVIRONMENT | `exception_info` 非空且在执行期；或 LongHorizon 模式：`Connection error.`、`response.failed`、`AGENT_EXIT=[1-9]` | ENVIRONMENT |
| `VERIFIER_FAILURE` | ENVIRONMENT | 无 `reward.txt` 或 verifier 超时 | ENVIRONMENT |
| `ORACLE_FAILED_HERE` | TASK | E0 中 oracle reward==0 | TASK（剔除） |

规则优先级（借 rollout-mvp `attribute()`）：ENVIRONMENT 类先判，命中即停止叠加 → TASK → FORMAT → BUDGET/PREMATURE → 其余按证据叠加（允许多标签）。

## 2. 判官层标签（软判，需证据 + onset）

| 标签 | TB 类 | 定义 | blame 候选 |
|---|---|---|---|
| `SPEC_MISINTERPRETATION` | Coherence | 产物内部自洽但与测试断言不符：输出路径 / 格式 / 边界情况理解不同（"做的是另一道题"） | MIXED |
| `GOAL_DRIFT` | Coherence | 压缩或长轨迹后行为偏离原任务 | MIXED |
| `ACKNOWLEDGED_BUT_IGNORED` | Coherence | 模型在 analysis 里说了有问题却照做（Strained Coherence） | MODEL |
| `INSUFFICIENT_VERIFICATION` | Verification | 宣布完成前最近 N 轮无 X/T/V 类动作（动作编码） | MIXED |
| `TEST_GAMING` | Verification | 修改测试 / 硬编码期望输出而非实现 | MODEL |
| `GAVE_UP` | Execution | 明确放弃或改做子集 | MODEL |
| `CAPABILITY` | — | 以上皆非，方向对但做不出来 | MODEL（对照组） |

判官同时输出 2609.20804 Table 9 的十类动作编码（I S C M E X T V N G → Understand / Write / Verify / Other），用于阶段面积图与终止阶段表。

## 3. 字段

- `onset_step`：最早出问题的 step（借 Fig.41 "最早失败阶段"约定；Failure as a Process）。
- `recovery_attempted: bool`：onset 之后是否有明显换思路的动作。
- `clarity`：题级，两个维度（UnderSpecBench：意图清晰度、目标确定性），每个维度用 SWE-bench Verified 的 **0–3 严重度**（0–1 轻微，2–3 严重）；任一维度 ≥2 记为模糊题。判官打分，30 题人工核对；同时对题目清单跑 `harbor check`（默认 11 条 rubric，含 `behavior_in_task_description`、`file_reference_mentioned`、`structured_data_schema`）作为官方口径的对照。报告"被标模糊的题占比"，对照 SWE-bench Verified 的 38.3%。

判官输出协议对齐 MAST 的标注器："一个主模式 + 引用证据"；κ 的报告方式照 MAST / TB 论文（人工间 κ、判官 vs 人工 κ 分开报）。

## 4. blame 规则（跨配置证据，非判官意见）

对每个模式 p，取噪声底 δ（第 2 天测得）：

| 换模型（同 harness）rate 变化 ≥ δ？ | 换 harness（同模型）变化 ≥ δ？ | blame |
|---|---|---|
| 否 | 是 | HARNESS |
| 是 | 否 | MODEL |
| 是 | 是 | MIXED |
| 否 | 否 | 属于 ENVIRONMENT/TASK 类则如此标；否则 UNKNOWN |

粒度是模式级，不是单条 trial 的因果；报告里写明。改动后仍存在的 MODEL / MIXED 模式 → 交接包（描述 + 3–5 条轨迹 + 已试过的缓解 + 建议题型），格式按 multi_agent_task_gen §6 `BadPattern`。

## 5. 与目标的对应

| 我们的改动 | 主要针对 |
|---|---|
| verifier_gate | PREMATURE_COMPLETION, INSUFFICIENT_VERIFICATION |
| adaptive_wait | POLLING, STUCK_AT_PROMPT |
| task_contract | SPEC_MISINTERPRETATION（模糊题子集） |
| assumption_ledger | GOAL_DRIFT（仅当 COMPACTION_OCCURRED 有发生） |
| stuck_reminder | LOOP |
| exit_code_prompt | COMMAND_NOT_FOUND 相关的重复失败 |
| budget_hint | BUDGET_EXHAUSTED |
| read_file_tool（延后） | TRUNCATED_READ |
