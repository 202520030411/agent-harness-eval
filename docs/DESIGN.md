# 评测流水线设计（agenteval）

目标：给定 Harbor 的一个 jobs 目录，自动产出每条 trial 的失败标签、按失败模式分组的统计、回归包和 A/B 对比；标签由规则层硬判、判官层软判、人工层复核，并由跨配置证据决定"归谁"。

## 0. 总览

```
harbor run（Terminus 2 / oracle / codex）
  └─ <jobs_dir>/<job_name>/<trial_name>/
        result.json                  task_name, agent_result.metadata{n_episodes, summarization_count, api_request_times_msec},
                                     verifier_result.rewards, exception_info, agent_setup / agent_execution / verifier 计时
        agent/trajectory.json        ATIF：steps[{step_id, source, message, reasoning_content,
                                     tool_calls[{function_name: bash_command|mark_task_complete, arguments{keystrokes,duration}}],
                                     observation.results[].content, metrics{prompt_tokens, completion_tokens, cached_tokens, cost_usd},
                                     extra.context_management}]
        verifier/reward.txt          0/1
  │
  ▼ ① adapters/harbor.py      读上面三样 → TrialRecord（统一 schema）
  ▼ ② attribute/rules.py      纯函数；规则标签 + blame 候选 + 证据；ENVIRONMENT 先判且排他
  ▼ ③ judge/                  盲评（看不到 reward、reasoning）：归因标签、TB 十类动作编码、指令清晰度、rubric 打分
  ▼ ④ rubric/                 强/弱配对 → rubric 条目 → 偏序验证（强侧得分必须系统性高于弱侧）
  ▼ ⑤ aggregate/vote.py       规则硬否决 > 判官软信号；冲突 → REVIEW 队列（人工标注入口）
  ▼ ⑥ store.py                错题集：SQLite 索引 + JSONL 快照，按 harness 配置版本化
  ▼ ⑦ blame.py                跨配置二维表 → MODEL / HARNESS / MIXED / ENVIRONMENT / TASK
  ▼ ⑧ report/                 四级指标、按模式分组、阶段面积图、终止阶段表、成本与 cache、A/B 配对检验
  ▼ ⑨ regression/             固定题目清单 + 门脚本（改崩返回非零退出码）
```

## 1. 目录结构

```
agent_harness/
  agenteval/                      pip 可装的包；入口 `agenteval analyze|compare|judge|label|regress`
    schemas.py                    TrialRecord / Step / FailureLabel / JudgeVerdict / RubricItem / ClarityRating
    score_configs.yaml            每个标签名的合法取值与类型（taxonomy.md 的机器校验版；写入前校验，不合法即拒）
    prompts/<name>/v<N>.txt       所有 harness / 判官提示词按版本存放；TrialRecord 记录用到的版本与 hash
    adapters/harbor.py            jobs 目录 → TrialRecord
    attribute/rules.py            规则层（纯函数，无 IO）
    attribute/signals.py          正则与阈值常量（含 LongHorizon runtime_signals 的模式）
    judge/views.py                轨迹渲染给判官：去 reasoning、去 reward、截断长输出
    judge/config.yaml             每个判官任务一条：提示词版本、变量映射（喂哪些 TrialRecord 字段）、抽样率、过滤条件（如只看失败 trial）
    judge/client.py               判官模型调用（家族 ≠ 被测模型）；缓存到磁盘按 (prompt_hash, model)
    rubric/writer.py              配对 → rubric 条目 + bad pattern
    rubric/validate.py            偏序检验（纯函数）
    aggregate/vote.py             硬否决 + 加权投票 → ACCEPT / REJECT / REVIEW
    store.py                      错题集
    blame.py                      二维表规则
    report/metrics.py             四级指标、成本、cache 份额、轮数
    report/stats.py               McNemar 配对、BH 校正、bootstrap 区间、噪声底
    report/figures.py             阶段面积图、失败分布图
    report/render.py              Markdown 报告
    regression/gate.py            回归门
    cli.py
  terminus2_patches/              对 Harbor 内 Terminus 2 的改动（fork 分支或 patch 文件），每个开关一个提交
  experiments/
    task_list.txt                 固定题目清单（第 2 天定）
    configs/*.yaml                每张表一个 Harbor 配置
    README.md                     E0–E9 命令与产物路径、钉死的版本
  tests/                          每个不变量一个测试；金标轨迹 5 条
  docs/DESIGN.md  docs/taxonomy.md
  HYPOTHESES.md  decisions.md  PLAN.md
```

## 2. 模块：输入 / 输出 / 移植来源

| 模块 | 输入 | 输出 | 移植自 | 测试 |
|---|---|---|---|---|
| `adapters/harbor.py` | trial 目录 | `TrialRecord` | 新写；字段对应上面的 ATIF 与 `result.json` | 5 条金标 trial 目录 → 固定 JSON |
| `attribute/rules.py` | `TrialRecord` | `list[FailureLabel]` | rollout-mvp `pipeline/runner.py:61` `attribute()` 的优先级链；taskengine `taskengine/failures/taxonomy.py` `classify()` 的 blame / confidence / evidence 与"环境原因能解释就不再叠加" | 每条规则一个正例一个反例 |
| `judge/views.py` | `TrialRecord` | 文本 | rollout-mvp `pipeline/agent/views.py:11` `render_trajectory`（去 reasoning）；加去 reward | 断言渲染结果不含 `reasoning_content` 与 reward |
| `judge/prompts/` | — | — | 归因：新写（输出固定控制头，见 §5）；动作编码：2609.20804 Fig.42 + Table 9 原样；清晰度：UnderSpecBench 两维度；rubric 打分：multi_agent_task_gen §5.3 | 提示词快照测试 |
| `rubric/validate.py` | rubric 条目 + 两侧打分 | 通过 / 丢弃 | multi_agent_task_gen/PROJECT.md §5.3 偏序规则 | 合成数据：强 > 弱 通过，反之丢弃 |
| `aggregate/vote.py` | 规则标签 + 判官标签 | 决定 + REVIEW 队列 | taskengine `taskengine/aggregate/vote.py:32` `aggregate()`（硬否决不可被软信号推翻） | 硬否决优先的用例 |
| `store.py` | 记录 | 持久化 | taskengine `taskengine/store.py:43` `Store` | 幂等写入 |
| `blame.py` | 各配置下的模式发生率 + 噪声底 δ | 模式 → blame | 新写，规则见 `taxonomy.md` §4 | 四象限各一个用例 |
| `report/metrics.py` | TrialRecord 集 | 指标表 | FirstCoder `benchmark/harbor/shared/summarize.py` 的四级划分 | 手算对照 |
| `report/stats.py` | 两配置逐题结果 | p、q、区间 | 2609.20804 §3.1（McNemar + BH） | 已知答案的小表 |
| `regression/gate.py` | 清单 + 两次运行 | 退出码 | FirstCoder `terminal-bench-ab-tasks.txt` 的做法 | 改崩一题 → 非零 |

## 3. 不变量（每条一个测试）

1. `terminus2_patches` 所有开关关闭时，发给模型的提示词与上游 Terminus 2 逐字节一致（复用 Harbor `tests/golden/terminus_2/*.trajectory.json` 的做法）。
2. 判官永远看不到 reward、reasoning_content、其他判官的输出。
3. 基础设施失败（`exception_info` 非空、agent setup 超时、verifier 无 reward、方舟连接错误）标为 ENVIRONMENT，且**不进任何能力统计**。
4. 规则层是纯函数：同一 TrialRecord 永远同一输出；无网络、无时钟。
5. 硬否决（规则层 ENVIRONMENT / PREMATURE_COMPLETION）不可被判官推翻。
6. 每个标签带 `evidence`（原文片段 + step_id）；没有证据的标签不允许写入。
7. blame 由跨配置证据决定，判官只提候选。
8. 过早完成只由规则判定（False Success 论文：判官看措辞不看状态）。
9. 判官输出不符合控制头格式 → 一次格式修复重试，仍失败 → `cannot_judge`，不猜。

## 4. TrialRecord 字段

命名对齐可观测性工具的三层（借 Langfuse 数据模型，便于以后导出）：**session = 一道题**（同题的所有 attempt 归组），**trace = 一条 trial**，**observation = 一轮**。

```
TrialRecord                      （= trace）
  trial_id, task_name（= session）, config_id（harness 开关组合 + 模型 + 种子）, attempt
  tags[]: 开关名列表；metadata{}: 自由键值
  prompt_versions{}: {"system": "v3@a1b2c3", "auditor": "v1@...", "judge_attr": "v2@..."}
  reward: 0|1|None            None = 没拿到明确判分
  status: ok | setup_failed | agent_error | verifier_error | timeout
  n_episodes, summarization_count, wall_clock_sec, api_request_times_msec[]
  tokens: prompt, completion, cached, cost_usd
  steps[]                        （= observation）
    step_id, source, message, keystrokes[], durations[], claimed_complete: bool,
    observation_text, truncated: bool, parse_error: bool, compaction_boundary: bool,
    usage{prompt, completion, cached, cost_usd}, latency_ms
  labels[]                       （= score，形状借 Langfuse Score）
    FailureLabel{name, data_type: CATEGORICAL|BOOLEAN|NUMERIC|TEXT, value,
                 source: RULE|JUDGE|HUMAN, config_id → score_configs.yaml,
                 tb_class, blame_candidate, confidence, comment（=证据原文 + step_id）, onset_step}
  judge: JudgeVerdict{labels[], action_codes[], clarity, rubric_scores{}, cannot_judge}
  decision: ACCEPT | REJECT | REVIEW
```

`score_configs.yaml` 示例：

```yaml
PREMATURE_COMPLETION: {data_type: BOOLEAN}
primary_failure:      {data_type: CATEGORICAL, categories: [PREMATURE_COMPLETION, POLLING, LOOP, STUCK_AT_PROMPT, FORMAT, TRUNCATED_READ, SPEC_MISINTERPRETATION, GOAL_DRIFT, ACKNOWLEDGED_BUT_IGNORED, INSUFFICIENT_VERIFICATION, TEST_GAMING, GAVE_UP, CAPABILITY, ENVIRONMENT, TASK]}
clarity_intent:       {data_type: NUMERIC, min: 1, max: 5}
rubric_partial:       {data_type: NUMERIC, min: 0, max: 1}
```

人工标注（第 4 天）走同一条路：标注文件里的每条记录也是 `FailureLabel{source: HUMAN}`，写入前过同一个校验；κ 直接在 RULE / JUDGE / HUMAN 三种 source 之间算。

## 5. 判官控制头（借 LongHorizon Auditor 的做法）

归因判官输出前三行固定：

```
Primary: <taxonomy.md 中的一个标签>
Onset: <step_id 或 unknown>
Confidence: high|medium|low
```

之后自然语言给证据。解析用正则；不合格重试一次（`build_role_auditor_format_repair_prompt` 的做法）。

## 6. Terminus 2 改动落点（文件行号基于 Harbor main，2026-09-21 克隆）

所有开关加在 `Terminus2Options`（`terminus_2.py:83–179`），默认关闭。

| 开关 | 落点 | 说明 |
|---|---|---|
| `verifier_gate: none / self_check / auditor` | `_get_completion_confirmation_message` 626–647；完成分支 1531–1539、1655–1662 | `self_check`：同一对话里让主模型逐条核对；`auditor`：独立调用，只给指令 + 终端历史，只读命令白名单，输出固定控制头，三项都过才放行 |
| `adaptive_wait: bool`, `wait_stable_sec: float` | `_execute_commands` 1323–1353 现在调 `send_keys(block=False)` → `_send_non_blocking_keys` 765–777 只是 sleep。**已有阻塞路径没被用**：`_TMUX_COMPLETION_COMMAND = "; tmux wait -S done"`（`tmux_session.py:19`）、`_prepare_keys` 612–637、`_send_blocking_keys` 747–763（`timeout <max> tmux wait done`） | 实现按 expect / pexpect 模型：先走哨兵 + 超时（超时 = 模型给的 duration，`block=True`）；超时才截屏，匹配交互提示正则（`[y/N]` `Password:` `--More--` `(END)`、行尾裸 `> `）并在观察里明说"命令在等输入"；再退化到"屏幕连续 `wait_stable_sec` 无变化"。交互程序（vim / REPL）让哨兵永不触发 → 正好落到正则分支 |
| `task_contract: bool` | 模板 `templates/terminus-json-plain.txt`；解析器 `terminus_json_plain_parser.py` 放行 `requirements` / `ambiguities` 字段；`run()` 1728 注入环境勘察摘要 | 第一轮只读：keystrokes 命中写操作黑名单（`>`、`>>`、`sed -i`、`rm`、`mv`、`cp`、`tee`、`touch`、`mkdir`、`pip install`、`apt`、`make`）即打回 |
| `assumption_ledger: bool` | 观察拼装 1531–1548 末尾追加 | 与 `task_contract` 配合；压缩后不丢 |
| `budget_hint: bool` | 同上 | "已用 N 轮 / 上限 M" |
| `stuck_reminder: bool` | `_run_agent_loop` 内检测 keystrokes 连续重复 | 阈值 5 提醒 / 8 终止（2609.20804 Fig.20 原文） |
| `exit_code_prompt: bool` | `tmux_session.py:392–405` `_tmux_start_session`，`bash --login` 后 `export PS1='[exit=$?] \w$ '` | 一行 |
| `read_file_tool: bool` | 解析器 + `_execute_commands` 分流 | **延后**：基线里 TRUNCATED_READ 率高才做；不做存档找回（2609.20804：无人用） |

**cache 规则：** 所有动态内容（账本、预算、提醒）只追加在最新一条观察的末尾；系统提示词在第 1 轮后不再变化。报告 `cached_tokens / prompt_tokens`。

## 7. 指标定义

| 指标 | 定义 |
|---|---|
| env_success | environment_setup 成功的 trial / 全部 |
| agent_setup_success | agent_setup 成功 / env 成功 |
| reward_only_pass | reward==1 / 有明确 reward 的 trial |
| end_to_end_pass | reward==1 / 全部 trial（无 reward 按 0） |
| pass@k（题级） | 该题 k 次里至少一次通过 |
| mean_turns | `n_episodes` 均值 |
| tokens_in / out / cached_share / cost_usd | 来自 metrics 求和；cached_share = cached / prompt |
| polling_turns | keystrokes 为空的轮数 |
| pattern_rate(p, config) | 带标签 p 的失败 trial / 该配置全部能力可评 trial（排除 ENVIRONMENT） |
| rubric_partial | 判官按题级 rubric 打分的均值（失败 trial 的分辨率） |
| noise_floor δ | 同配置两个种子的 end_to_end_pass 之差的绝对值（10 题 k=5） |

A/B 对比：逐题配对；McNemar 精确检验；多组比较 BH 校正 q<0.05；bootstrap（题级重抽样 10,000 次）给差值区间；措辞用"方向一致"，不用"显著"。

k 次运行的聚合同时报两种 reducer（借 Inspect AI 的 `--epochs` 词汇）：`mean`（trial 级平均通过率）与 `pass@k`（题级至少一次通过）。

标配图：**帕累托图**——每个配置一个点，x = 每题平均成本（美元），y = end_to_end_pass；弱模型、强模型各一张（借 HAL 的成本受控评测）。拐杖判定看点在前沿上的移动方向。

## 8. 配对设计

| 配对 | 固定 | 变化 | 提炼 |
|---|---|---|---|
| A | harness = Terminus 2 | Seed vs 强模型 | 模型侧 pattern |
| B | 模型 = 同一 GPT-5.x | Terminus 2 vs Codex | harness 侧 pattern |
| C | 模型 = Seed | Terminus 2 基线 vs 各开关 | 我们的消融 |

## 9. 待确认

- Harbor 配置里数据集写法：`datasets: - name: terminal-bench` + `version:`，还是 `name: "terminal-bench@2.1"`；第 1 天 `harbor dataset list` 核对。
- Seed 的上下文窗口与 `model_info` 填法（`max_input_tokens` 影响 Terminus 2 压缩触发点）。
- Codex 在 Harbor 里的模型指定方式（`examples/configs/agents/codex-job.yaml`）。
- `trial_name` 命名规则，adapter 从目录名还是 `result.json` 取 task_name（用后者）。

## 10. 直接复用 Harbor 自带的三样（不重造）

| 命令 | 用途 | 在我们流程里的位置 |
|---|---|---|
| `harbor view jobs` | 本地网页：回放轨迹、token / 耗时拆分、多 job 并排比较矩阵、键盘导航 | 第 4 天人工标注的阅读界面；消融的逐题对比先看它 |
| `harbor analyze <job> --failing --rubric <our.toml>` | 评测 agent 在容器里读 trial 文件，按 rubric 逐条 pass / fail / not_applicable + 解释，写 `analysis.json`（`src/harbor/analyze/`；默认 rubric `analyze-rubric.toml`：`reward_hacking`、`task_specification`） | **判官 #2**：taxonomy 导出成 rubric（`criteria[] = {name, description, guidance}`），与我们判官、人工三方算 κ（HYPOTHESES M7） |
| `harbor check <tasks>` | 题目质量 rubric（`src/harbor/cli/quality_checker/default-rubric.toml`，11 条） | E0 对题目清单跑一遍，作为官方口径的题目质量报告，和我们的 clarity 打分对照 |

`score_configs.yaml` 与 Harbor 的 rubric 形状保持可互转：我们的 `name` / `data_type` / `categories` ↔ 它的 `name` / `description` / `guidance`。
