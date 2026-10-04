# 人工标注指南（第 4 天，约 2 小时，39 条）

目的：给判官打分——你的标签是"真值"，判官和规则层都拿来和你比一致率（κ）。所以**先别看表里最后两列（判官的答案）**，标完再对。

## 怎么看轨迹

1. Mac 终端开一个端口转发（把服务器上的网页拉到本机）：
   ```bash
   ssh -L 8080:127.0.0.1:8080 root@<your-server> 'export PATH=$HOME/.local/bin:$PATH; harbor view /root/work/jobs --port 8080'
   ```
2. 浏览器打开 http://127.0.0.1:8080 → 选 job `e1-baseline-seed` → 点某条 trial → 逐轮看命令、终端输出、verifier 输出。键盘 `j`/`k` 上下，`Enter` 打开。
3. 标注表：`reports/e1-baseline-seed.labeling_sheet.csv`（用 Numbers / Excel 打开），一行一条失败 trial，`trial_id` 对应网页里的名字。

## 每条填什么

| 列 | 填 |
|---|---|
| `human_primary` | 下面标签里**选一个**：最早把这条 trial 带偏的那个原因（最早失败约定：后面的症状不算） |
| `human_onset` | 出问题的那一轮 `step_id`（网页里每轮有编号）；看不出就写 `unknown` |
| `human_secondary` | 可选，逗号分隔。**一条失败常是因果链**（先理解错题意 → 交付错 → 没查就说完成）：链上最早的填 primary，后面的填这里；算一致率时有"主标签落在对方主/次标签里"的宽松口径 |
| `human_notes` | 一句话证据：引用命令或终端输出 |
| `clarity_intent_0_3` | 指令的"意图清晰度"缺陷严重度：0 无问题，1 轻微，2 严重（缺了关键信息但环境里能找到），3 严重（缺了且找不到）|
| `clarity_target_0_3` | 指令的"目标确定性"（改哪个文件 / 输出到哪 / 什么格式）缺陷严重度，同上 |

## 标签定义

**Verification（验证类）**
- `PREMATURE_COMPLETION`：宣布完成前，用它手头的信息本可以做一个检查发现问题，但没做。
- `INSUFFICIENT_VERIFICATION`：做了检查，但检查方式抓不到这个错（比如自己写的测试测的不是题目要的行为）。
- `TEST_GAMING`：改测试、硬编码期望输出、绕过判题。

**Coherence（一致性类）**
- `SPEC_MISINTERPRETATION`：做的是另一道题——路径 / 格式 / 边界情况 / 目标理解错，且指令里其实写了或环境里能查到。
- `GOAL_DRIFT`：中途忘了原目标，去干别的。
- `ACKNOWLEDGED_BUT_IGNORED`：自己说了"这里有问题"，然后照做不改。

**Execution（执行类）**
- `LOOP`：同一个失败动作反复做。
- `POLLING`：大量空等待。
- `STUCK_AT_PROMPT`：命令在等输入（`[y/N]`、密码、分页器），agent 没应答。
- `TRUNCATED_READ`：文件输出被截断了，agent 基于残缺内容去改。
- `FORMAT`：反复输出格式错误。
- `BUDGET_EXHAUSTED`：还在正常推进，时间 / 轮数用完了。
- `COMMAND_ERRORS`：一连串命令找不到 / 缺依赖，一直没解决。

**其他**
- `GAVE_UP`：明确放弃或只做了子集。
- `CAPABILITY`：思路对，就是做不出来。
- `ENVIRONMENT`：容器 / 工具坏了，不是 agent 的问题。
- `TASK_UNDERSPECIFIED`：指令没写、环境里也查不到测试要求的东西——题目的问题。

## 两个原则

- agent 自己说的话（"我已经验证了"）不是证据；终端输出和命令才是。
- 拿不准就在 notes 里写"A 或 B"，不要硬选；一致率算的时候会单独处理。
