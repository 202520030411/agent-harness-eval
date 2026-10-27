# Coding Agent 失败归因与 Harness–模型协同迭代

[English](README.md) | **中文**

**一句话：** coding agent 在终端任务上失败时，问题出在模型、**harness**（模型外面那层控制程序：提示、工具接口、等待方式、交卷检查）还是题目本身？本项目在 [Terminal-Bench 2.1](https://github.com/harbor-framework/terminal-bench-2-1)（通过 [Harbor](https://github.com/laude-institute/harbor)）上用对照实验回答这个问题：先用评测流水线自动归因失败（规则 + 两家 LLM 判官 + 人工校验 + rubric 偏序验证）；能靠 harness 修的失败逐个改、逐个消融；模型侧的残余做成合成题去训练；最后把 harness 这一侧做成带统计门的自进化闭环。研究了两个模型：**Seed 2.1 lite**（API）和 **Qwen3-Coder-30B-A3B**（自己用 vLLM 部署在一张 H200 上）。每个设计决定都记在 [`decisions.md`](decisions.md)（D-001 – D-097），每个预测都在跑之前写进 [`HYPOTHESES.md`](HYPOTHESES.md)。

**这不是 toy 的四个理由：** 先测噪声底（δ = 8 pp）再谈"有效"；先写预测再跑（`HYPOTHESES.md`，跑完只填不改）；每个改动都在强模型上再跑一遍做"拐杖判定"；判官自己也被验证（两家一致率、不变性测试、人工标注）。

## Seed 2.1 lite 上的结论（2026-09-24）

- **基线**：Seed lite × Terminus 2，41 题 × k=3：trial 级 68.3%，pass@3 82.9%，0.155 元/trial。同题 gpt-6-sol k=1：92.7%（+27.5 pp [16.7, 39.2]）。
- **噪声底**：同配置两次重跑（10 题 × k=5）差 8 pp → 任何 < 8 pp 的"提升"都不算数（M1 证伪了"δ ≤ 3 pp"的预期）。
- **失败在哪**：规则把 64% 失败标成"没验证就说完成"，判官再拆成 36% 题意误读 + 21% 验证不足 + 8% 题目本身不清；14/41 题被判"题面模糊"，这类题基线 52.4% vs 清晰题 76.6%。
- **五种 harness 改动（26 题 × k=3，同批次基线 61.5%）**：没有一个越过 8 pp；`task_contract` 的收益集中在模糊题（首批 +13.9 pp vs 清晰题 +2.4；把模糊题补到每题 6 次后收缩为 +6.7 [−5.2, +21.4]，且几乎全由 extract-elf 一道题贡献；四批合并、每题 12 次后为 +4.8 [−3.0, +13.1]，预注册的第四批 H17 没有复现子集效应，D-050），判官标签里题意误读 13→9；`auditor` 打回都对但模型补不完，+29% 成本换来 +0.0；`adaptive_wait` 空等待轮 −27%、token −11%、通过率不变；`stuck_reminder` 一次都没触发。
- **拐杖判定**（同样 26 题在 gpt-6-sol 上 k=2 重跑）：`task_contract` −1.0 pp、成本 +57%；`self_check` −2.1 pp、成本 +79%、轮数 11.6 → 20.5。两者都是只对弱模型（方向上）有用的"拐杖"，强模型不涨反而多付钱；只有 `adaptive_wait` 是省资源不动决策的结构性改动。
- **归责**：BUDGET_EXHAUSTED、TRUNCATED_READ 换强模型后消失、改 harness 不变 → 模型侧；PREMATURE_COMPLETION 两边都动 → 混合。交接包见 `reports/e4/handoff_model_patterns.md`。
- **判官自己靠不靠谱**：换一家判官（claude-sonnet-5）重判同样 39 条失败，主标签 κ 只有 0.49（预注册要求 0.80，证伪）；分歧几乎都在"题意误读 / 验证不足 / 过早完成"三者之间，而"预算耗尽"10/13 一致；把对方的次标签也算上（失败是因果链，两家常各指一环），一致率 79.5%。所以报告里细粒度标签只当线索，结论用 TB 三大类 + 人工仲裁。
- **改题不改 harness（E8）**：把判官指出的接口约定写进 5 道“题面模糊”题的说明后重跑。extract-elf 从 0/6 变 3/3，cancel-async 2/6 变 3/3；raman-fitting 和 dna-insert 仍 0/3；再把缺口补到底（E8b，泄露式）：dna 3/3（是题 + 环境的锅：边界约定和 oligotm 版本），raman 给了 1e7/x 换算后峰位全对、仍卡在题面没说的拟合窗口上。判官的“题目不清”要拆成接口约定 / 领域知识 / 环境工具三类，只有第一类改题就好。
- **判官对措辞敏感（M3）**：只把模型自述改写得更自信 / 更犹豫，命令和输出不动，gpt-6-sol 的主标签翻转 27% / 30%（预注册 ≤ 5%，证伪）；翻转发生在“题目不清 ↔ 题意误读”“预算耗尽 ↔ 能力不足”这两对相邻标签之间，和两家判官互相的分歧模式一致。但对照（原文不改、重判一次）也翻 23%，所以措辞本身的净效应在噪声内；真正的发现是判官自身复判一致率只有 77%，判官要用 temperature=0 或多数投票才能当尺子。
- **判官 vs 参考标签**：39 条 E1 失败的参考标签里，16 条由作者定案、16 条在模型辅助下核对或改判、2 条未标来源、5 条是三家判官一致后直接采用；最后这 5 条有循环之嫌，下面的主要数字去掉它们。剩下 34 条上，给判官隐藏测试和参考解、再加上人工仲裁提炼的五条判定规则（v3），严格一致率从 **44% 升到 65%**（κ 0.33 → 0.56）；规则是从同一批的一部分写出来的，所以部分是样本内。严格口径的样本外检验（15 条未参与写规则）v3 与旧判官持平（0.57 vs 0.58）——规则消掉的是系统性归责错误（题面缺信息命中 3/8 → 6/8），剩下的是主次颠倒；同样的规则给 claude-sonnet-5 后它在样本外 15 条上 κ 0.66，说明规则不是只拟合了一家的错法。两家判官在这 34 条里一致 **50%**，一致的那部分准确 **82%**——所以最终的判官设计是“双判官一致就采信、不一致送人工”。换 5 倍价格的 gpt-6-astra 当判官并不更准（39 条口径 κ 0.55 vs 0.62），瓶颈不在模型强度。39 条参考标签的分布：题面缺信息 8、验证不足 8、能力 9、预算耗尽 8、题意误读 5、环境 1。

## Qwen3-Coder-30B-A3B 的四臂实验（2026-09-27，自己的 H200 + vLLM，TB 2.1 干净 30 题 × 4 次/臂）

- **通过率**：Terminus 原样 16% → 接口修补 21% / 再加交卷把关 22% / Qwen 官方 harness（qwen-code）22%；三个都 +5–6 pp，但 95% 区间都含 0，不显著。
- **接口修补管用的地方很具体**：宽松解析把每 trial 浪费的格式错误轮从 2.6 降到 0.17（−93%），跑满 100 轮上限的 trial 从 9 降到 1；build-pmars 1/4 → 4/4、log-summary 0/4 → 3/4。开跑前告诉模型“哪些命令没装”则没有用（命令不存在 40% → 38%）。
- **echo 代替检查是接口产物**：Terminus 里失败 trial 的 59% 这样做，qwen-code 里只有 2%——模型有了直接用文字回复的地方就不再借 echo“说话”；但“明知没做成仍宣布完成”只是从 echo 挪进了文字（任何 harness 下都占失败的 23–31%）。
- **交卷把关**打回了 37/120 个 trial，最后通过的只有 4 个：能逼模型去查，查出来也修不好。预注册的 H2 预测被证伪。
- **归责**：格式错误 → harness；假成功与能力缺口（17 道三次全挂的题里 15 道在任何 harness 下都不过）→ 模型侧，是训练目标。细节见 `docs/QWEN_PLAN.md` 的“2–3 的结果”与 D-053–D-059。

## 针对模型侧残余的训练（2026-09-27 – 09-28，Qwen，D-073、D-076、D-083）

- **合成题**：111 道 Harbor 格式的合成题（验证过：参考解能过、什么都不做不能过、和 TB 去重），74 道开发、37 道留出。
- **拒绝采样微调**：只用 Qwen 自己做对的轨迹做 LoRA SFT；再做 GRPO，由强模型看着它做题、在走偏时插一句提示。在它从没做对过的题上，实时提示在采样时把通过率做到 **25%**，开头只给一次提示只有 **5–6%**。
- **结果（留出 37 题 × 3 次，三组同时跑）**：原版 16%、SFT 14%、RL 16%；RL − 原版 **+0.0 pp**，95% 区间 [−7.2, +7.2]。TB 30 题 × 4 次：24% / 18% / 21%，都不显著。提示的帮助没有迁移：撤掉提示后 72% → 8%（不带提示的试做合计 8/282）。第一次 SFT 评测里看起来显著的"明知没做成仍宣布完成"下降（11% → 4%），在同时跑的重复评测里没有复现（10% vs 9%）。
- **结论**：这一轮训练在新题和 TB 上都没有带来可测的提升；预注册的三条 RL 预测都不成立（D-083）。

## Harness 自进化闭环（2026-10-11 – 10-15，Qwen，D-084 – D-097）

代码在 `agenteval/loop/`、`tools/loop_cycle.py`，完整说明见 [`experiments/loop/README.md`](experiments/loop/README.md)。流程：观察轨迹 → 找失败模式 → 大模型提出改动并预先登记预测 → 新旧版本在 74 道开发题 × 4 次上同时跑、按题配对 → 过统计门才采纳。

- **先加固判分。** 合成题原来在做题的同一个容器里判分；用脚本写的作弊演习（8 种手法，不调模型）骗过旧版 **16/24**，判分改到单独的容器（只带走 `/app`、重放题目构建、放诱饵答案文件）后 **0/24**。这个案例的 2,184 次试跑里，碰诱饵 0、作弊嫌疑标记 0。
- **统计门**（`agenteval/loop/accept.py`）：按题配对 bootstrap；"真的更好"要通过率区间 > 0 且 ≥ 8 pp，"更省且不更差"要轮数 / 输入 token / 分钟至少一项降 ≥ 10%（各用 alpha/3）且通过率区间下界 ≥ −min(8 pp, 基线 × 25%)；同配置随机对半分校准：误判为更好 **2.5–6%**、误判为更差 **5.5–9%**；两臂没同时跑、整题丢失、机器故障 > 5% 一律判无效。
- **唯一通过的改动 `append_nudge`：** Qwen 常常一轮只用 `echo >>` 往文件里接一行代码（开发集 26% 的尝试，这类尝试约 230 个只过 1 个），harness 在它连续第 3 轮这样做时附一句"用一条命令写完整个文件"、不占模型轮次。这个习惯减少 **92–95%**，开发集和 37 道留出题上总轮数降 **21–30%**、输入 token 降 **24–31%**，通过率没有可靠变化（+1.6、+3.4、−1.8 pp，区间都含 0）；每题墙钟时间没变（输出 token 总量不变、每轮更长）。
- **第 1 轮被自己的护栏误拦：** 以前撞 100 轮上限的尝试（43 → 1）现在能交卷但多数仍做错，被当成"提早放弃"；交了卷的里面做错的比例其实不变（78.2% vs 78.5%）。没有改判那一轮：修护栏、重新校准（误判率不变），在新数据上按代码里写死的一次性重测通过（轮数 −21%、token −24%、通过率 +3.4 [−0.3, +7.4]）。复现批因 GPU 机器余额耗尽断电判无效，按规则**没有上线**。
- **TB 上 +10 pp 是噪声：** 提醒只在 30 道题里的 3 道发出过，多出的 9 次通过里 8 次来自没发过提醒的题（那里两版提示逐字相同）。
- **这个毛病从哪来：** 第一轮的观察只按固定规则数已知失败类型，看不到它；是开发闭环时做轨迹统计发现、再加成规则的。之后的"自动找毛病"（两个判官模型读 80 条失败轨迹，清单里故意不写这个毛病）独立找回了它，召回 **56%**。
- **提议模型改写自己的 prompt：** prompt 分可改写的 playbook（[`P0`](experiments/loop/playbooks/P0.md) → [`P1`](experiments/loop/playbooks/P1.md)）和固定的输出格式，范围限制、防泄题过滤、给 agent 看的文字要人批准都写在代码里。P1 学会了"提议之前先估算目标行为多常见、最多能省多少"（之前 3 个候选正是因此被撤下）；下一轮 P0、P1 都没有提出值得测的改动，Qwen 自己当提议者给出的是一个重复和一个换了说法、预测对不上机制的候选。"交卷时自己的检查已经报错就打回"离线模拟准确率 90–100%，但最多影响约 10% 的尝试，这个样本量测不出来，没有花钱测。

## 流水线

```
harbor run ──▶ jobs/<job>/<task>__<id>/{result.json, agent/trajectory.json, verifier/}
                 │
                 ▼ adapters/harbor.py                TrialRecord（statuses: ok / setup_failed / agent_error / verifier_error / agent_timeout）
                 ▼ attribute/rules.py                规则标签（PREMATURE_COMPLETION, BUDGET_EXHAUSTED, POLLING, LOOP, TRUNCATED_READ, INTEGRITY_SUSPECT …）
                 ▼ judge/attribution.py              LLM 判官（gpt-6-sol；第二家 claude-sonnet-5）→ 主标签 / 起始轮 / 置信度
                 ▼ judge/aux.py                      题面清晰度 0–3、动作编码、终止方式
                 ▼ rubric/pipeline.py                强/弱模型同题 rubric 偏序验证
                 ▼ report/{metrics,stats,compare}    4 级指标、配对 McNemar + BH、题级 bootstrap CI、噪声底
                 ▼ report/{agreement,blame,handoff}  判官一致率 κ、归责 2×2、交接包
                 ▼ regression/gate.py                回归门（退出码）
```

## 命令

| 命令 | 作用 | 产物 |
|---|---|---|
| `agenteval analyze <job>` | 读 job → 规则标签 → 指标 | `summary.{md,json}`, `trials.jsonl` |
| `agenteval judge <job> --model gpt-6-sol [--blind]` | 失败 trial 的判官归因 | `judge/judge.jsonl` |
| `agenteval report <job>` | 规则 × 判官交叉表 + 人工标注表 | `crosstab.md`, `labeling_sheet.csv` |
| `agenteval clarity` / `actions` | 题面清晰度 / 动作编码与终止统计 | `clarity.jsonl`, `actions.jsonl`, `termination.json` |
| `agenteval compare <A> <B>` | 配对比较（McNemar、bootstrap CI、子集） | `compare.md` |
| `agenteval rubric <strong> <weak>` | rubric 生成 + 偏序验证 | `rubric/` |
| `agenteval agreement <x.jsonl> <y.csv>` | 判官 vs 判官 / 判官 vs 人工：一致率 + κ | `agreement_*.md` |
| `agenteval invariance <job>` | 只改自述措辞重判，看标签翻转率（M3） | `invariance.jsonl` |
| `agenteval blame --weak-base … --strong-mod … [--handoff]` | 归责 2×2 + 交接包 | `blame_*.md`, `handoff_*.md` |
| `agenteval regress <A> <B> --tasks regression_tasks.txt` | 回归门，退化则退出码 1 | 表 + `GATE PASSED/FAILED` |

自进化闭环：`python tools/loop_cycle.py observe | reflect | discover | propose | rewrite-playbook | plan | evaluate | promote …`（产物在 `reports/loop/`；`plan` 只写配置、不启动，评测前要人批准）。

Harness 侧：`terminus2_patches/agent.py::Terminus2Patched`（`-a terminus2_patches.agent:Terminus2Patched`），开关 `interface_fixes`、`completion_gate`、`adaptive_wait`、`deliverable_checkpoint`、`verifier_gate`、`task_contract`、`append_nudge`，闭环用的文字类选项 `custom_notes`、`skills`，以及只用于训练采样的 `teacher_hint`；全关时与上游逐字相同（golden 测试）。已退役的开关（`stuck_reminder`、`budget_hint`、`exit_code_prompt`、`assumption_ledger`）见 D-039。

## 文件索引

| 文件 | 内容 |
|---|---|
| `HYPOTHESES.md` | 预注册：每个改动针对什么、预测什么、什么算证伪；结果列已回填 |
| `experiments/README.md` | E0–E9 编号、命令、结果表（E4 六臂 + 判官表 + 强模型臂） |
| `experiments/e8_rewrites/` | E8 改题文本与原则 |
| `docs/DESIGN.md` / `docs/taxonomy.md` | 流水线设计；失败分类（对齐 TB 论文三大类）与归责规则 |
| `docs/LABELING.md` | 人工标注手册（`harbor view` 回放、标签定义、0–3 清晰度） |
| `docs/LAB_NOTEBOOK.md` | **实验日志**：中途读数及其后来的变化、每次转向的理由链、贯穿全程的方法论教训 |
| `docs/QWEN_PLAN.md` | **Qwen 的 bad pattern 责任拆分**：哪些归 harness（四臂同时对照）、哪些归训练（只训残余），以及两侧怎么做 |
| `docs/TRAINING_PLAN.md` | **针对性训练计划**（预注册）：把评测找出的坏模式变成合成任务，拒绝采样 + LoRA SFT，回到同一条流水线验证；代码在 `train/ambig/` |
| `docs/DESIGN_alignment.md` | 第三圈蓝图：题面—验收对齐层（五段流水线、每段指标、横切规则） |
| `docs/harbor_pr_draft.md` | 给 Harbor 上游的 PR 草稿（死超时分支 + 可选哨兵等待） |
| `decisions.md` | D-001–D-097：每个设计决定的备选、理由、代价 |
| `experiments/loop/README.md` | **自进化闭环**：各步做什么、接受门怎么校准、判分加固和作弊演习、每一轮的结果 |
| `agenteval/loop/` | 闭环代码：失败模式、找毛病、提议与 playbook 改写、防泄题过滤、可改范围、版本登记、接受门 |
| `experiments/loop/` | 闭环的版本登记表、预注册、playbook（P0 / P1） |
| `reports/` | 本地报告副本：E1 交叉表、E4 compare、图、归责表、交接包 |
| `PLAN.md` | 原排期（已被"做完就继续"取代，留作预算/风险参考） |

## 钉死版本

Harbor 0.23.0；数据集 `terminal-bench/terminal-bench-2-1`（89 题，用 41 + 12 备选，3 题因验证器问题排除）；被测 `doubao-seed-2-1-lite-260915`（1024k，thinking 默认开）和 `Qwen3-Coder-30B-A3B-Instruct`（自己的 vLLM，H200，bf16）；强模型 / 判官 `gpt-6-sol`；第二判官 `claude-sonnet-5`；辅助判官 `gpt-6-luna`。运行机：Hetzner CPX62（16 vCPU / 30 GB）。

## 数据说明

所有题目来自 Terminal-Bench 2.1（89 题中的 41 + 12 备选）。TB 的题面与测试文件带有 canary（不得进入训练语料），因此本仓库公开版**不包含**：题面原文、隐藏测试、改写后的题面、完整轨迹标注包、判官原始输出（引用了测试内容）。这些在 `.gitignore` 里；报告只引用题名和汇总数字。
