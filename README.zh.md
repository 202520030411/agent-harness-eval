# Coding Agent 失败模式自动诊断与 Harness 迭代闭环

**一句话：** 在 Terminal-Bench 2.1 上，固定被测模型（火山方舟 Seed 2.1 lite），只改 Terminus 2 的 harness：先用评测流水线自动找出失败模式（规则 + LLM 判官 + 第二家判官 + 人工校验 + rubric 偏序验证），再按"机制 → 失败类"逐个改 harness、逐个消融，最后把每类失败归到 **模型侧 / harness 侧 / 混合**，并把模型侧的打成交接包。

**这不是 toy 的四个理由：** 先测噪声底（δ = 8 pp）再谈"有效"；先写预测再跑（`HYPOTHESES.md`，跑完只填不改）；每个改动都在强模型上再跑一遍做"拐杖判定"；判官自己也被验证（两家一致率、不变性测试、人工标注）。

## 到目前为止的结论（2026-09-24）

- **基线**：Seed lite × Terminus 2，41 题 × k=3：trial 级 68.3%，pass@3 82.9%，0.155 元/trial。同题 gpt-6-sol k=1：92.7%（+27.5 pp [16.7, 39.2]）。
- **噪声底**：同配置两次重跑（10 题 × k=5）差 8 pp → 任何 < 8 pp 的"提升"都不算数（M1 证伪了"δ ≤ 3 pp"的预期）。
- **失败在哪**：规则把 64% 失败标成"没验证就说完成"，判官再拆成 36% 题意误读 + 21% 验证不足 + 8% 题目本身不清；14/41 题被判"题面模糊"，这类题基线 52.4% vs 清晰题 76.6%。
- **五种 harness 改动（26 题 × k=3，同批次基线 61.5%）**：没有一个越过 8 pp；`task_contract` 的收益集中在模糊题（首批 +13.9 pp vs 清晰题 +2.4；把模糊题补到每题 6 次后收缩为 +6.7 [−5.2, +21.4]，且几乎全由 extract-elf 一道题贡献；四批合并、每题 12 次后为 +4.8 [−3.0, +13.1]，预注册的第四批 H17 没有复现子集效应，D-050），判官标签里题意误读 13→9；`auditor` 打回都对但模型补不完，+29% 成本换来 +0.0；`adaptive_wait` 空等待轮 −27%、token −11%、通过率不变；`stuck_reminder` 一次都没触发。
- **拐杖判定**（同样 26 题在 gpt-6-sol 上 k=2 重跑）：`task_contract` −1.0 pp、成本 +57%；`self_check` −2.1 pp、成本 +79%、轮数 11.6 → 20.5。两者都是只对弱模型（方向上）有用的"拐杖"，强模型不涨反而多付钱；只有 `adaptive_wait` 是省资源不动决策的结构性改动。
- **归责**：BUDGET_EXHAUSTED、TRUNCATED_READ 换强模型后消失、改 harness 不变 → 模型侧；PREMATURE_COMPLETION 两边都动 → 混合。交接包见 `reports/e4/handoff_model_patterns.md`。
- **判官自己靠不靠谱**：换一家判官（claude-sonnet-5）重判同样 39 条失败，主标签 κ 只有 0.49（预注册要求 0.80，证伪）；分歧几乎都在"题意误读 / 验证不足 / 过早完成"三者之间，而"预算耗尽"10/13 一致；把对方的次标签也算上（失败是因果链，两家常各指一环），一致率 79.5%。所以报告里细粒度标签只当线索，结论用 TB 三大类 + 人工仲裁。
- **改题不改 harness（E8）**：把判官指出的接口约定写进 5 道“题面模糊”题的说明后重跑。extract-elf 从 0/6 变 3/3，cancel-async 2/6 变 3/3；raman-fitting 和 dna-insert 仍 0/3；再把缺口补到底（E8b，泄露式）：dna 3/3（是题 + 环境的锅：边界约定和 oligotm 版本），raman 给了 1e7/x 换算后峰位全对、仍卡在题面没说的拟合窗口上。判官的“题目不清”要拆成接口约定 / 领域知识 / 环境工具三类，只有第一类改题就好。
- **判官对措辞敏感（M3）**：只把模型自述改写得更自信 / 更犹豫，命令和输出不动，gpt-6-sol 的主标签翻转 27% / 30%（预注册 ≤ 5%，证伪）；翻转发生在“题目不清 ↔ 题意误读”“预算耗尽 ↔ 能力不足”这两对相邻标签之间，和两家判官互相的分歧模式一致。但对照（原文不改、重判一次）也翻 23%，所以措辞本身的净效应在噪声内；真正的发现是判官自身复判一致率只有 77%，判官要用 temperature=0 或多数投票才能当尺子。
- **判官 vs 人工**（39 条 E1 失败全部人工定案）：旧判官（半盲、单次）κ 0.40；给全 context 并三票 κ 0.50；再加上人工仲裁提炼的五条判定规则（v3）κ 0.62、宽松一致 97%、无弃权。严格口径的样本外检验（15 条未参与写规则）v3 与旧判官持平（0.57 vs 0.58）——规则消掉的是系统性归责错误（题面缺信息命中 3/8 → 6/8），剩下的是主次颠倒；同样的规则给 claude-sonnet-5 后它在样本外 15 条上 κ 0.66，说明规则不是只拟合了一家的错法。两家 v3 互相 κ 只有 0.47，但一致的 22/39 条对人工正确 86%——所以最终的判官设计是“双判官一致就采信、不一致送人工”，自动处理 56% 的案子，人工只看剩下的。换 5 倍价格的 gpt-6-astra 当判官并不更准（κ 0.55 vs 0.62），瓶颈不在模型强度。人工定案分布：题面缺信息 8、验证不足 8、能力 9、预算耗尽 8、题意误读 5、环境 1。

## Qwen3-Coder-30B-A3B 的四臂实验（2026-09-27，自己的 H200 + vLLM，TB 2.1 干净 30 题 × 4 次/臂）

- **通过率**：Terminus 原样 16% → 接口修补 21% / 再加交卷把关 22% / Qwen 官方 harness（qwen-code）22%；三个都 +5–6 pp，但 95% 区间都含 0，不显著。
- **接口修补管用的地方很具体**：宽松解析把每 trial 浪费的格式错误轮从 2.6 降到 0.17（−93%），跑满 100 轮上限的 trial 从 9 降到 1；build-pmars 1/4 → 4/4、log-summary 0/4 → 3/4。开跑前告诉模型“哪些命令没装”则没有用（命令不存在 40% → 38%）。
- **echo 代替检查是接口产物**：Terminus 里失败 trial 的 59% 这样做，qwen-code 里只有 2%——模型有了直接用文字回复的地方就不再借 echo“说话”；但“明知没做成仍宣布完成”只是从 echo 挪进了文字（任何 harness 下都占失败的 23–31%）。
- **交卷把关**打回了 37/120 个 trial，最后通过的只有 4 个：能逼模型去查，查出来也修不好。预注册的 H2 预测被证伪。
- **归责**：格式错误 → harness；假成功与能力缺口（17 道三次全挂的题里 15 道在任何 harness 下都不过）→ 模型侧，是训练目标。细节见 `docs/QWEN_PLAN.md` 的“2–3 的结果”与 D-053–D-059。

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

Harness 侧：`terminus2_patches/agent.py::Terminus2Patched`（`-a terminus2_patches.agent:Terminus2Patched`），开关 `verifier_gate`、`adaptive_wait`、`task_contract`、`assumption_ledger`、`budget_hint`、`stuck_reminder`、`exit_code_prompt`；全关时与上游逐字相同（golden 测试）。

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
| `decisions.md` | D-001–D-059：每个设计决定的备选、理由、代价 |
| `reports/` | 本地报告副本：E1 交叉表、E4 compare、图、归责表、交接包 |
| `PLAN.md` | 原排期（已被"做完就继续"取代，留作预算/风险参考） |

## 钉死版本

Harbor 0.23.0；数据集 `terminal-bench/terminal-bench-2-1`（89 题，用 41 + 12 备选，3 题因验证器问题排除）；被测 `doubao-seed-2-1-lite-260915`（1024k，thinking 默认开）；强模型 / 判官 `gpt-6-sol`；第二判官 `claude-sonnet-5`；辅助判官 `gpt-6-luna`。运行机：Hetzner CPX62（16 vCPU / 30 GB）。

## 数据说明

所有题目来自 Terminal-Bench 2.1（89 题中的 41 + 12 备选）。TB 的题面与测试文件带有 canary（不得进入训练语料），因此本仓库公开版**不包含**：题面原文、隐藏测试、改写后的题面、完整轨迹标注包、判官原始输出（引用了测试内容）。这些在 `.gitignore` 里；报告只引用题名和汇总数字。
