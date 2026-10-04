# 排期与前置条件

## 你要准备的（到齐才能开第 1 天）

1. 一台 Linux 云服务器：Ubuntu 24.04，8 核 / 32 GB / 200 GB，**境外节点**（拉 Docker Hub / GitHub 镜像），给我 SSH 登录方式。
2. 火山方舟 API key + Seed 模型 ID + **它的上下文窗口大小**（决定压缩相关改动碰不碰，见 `decisions.md` D-004）。
3. 判官用的另一家 key（Anthropic 或 OpenAI 二选一）。第 9 天跑 Codex 对比需要 OpenAI key；跑 Claude Code 对比需要 Anthropic key。

## 10 个工作日

| 天 | 做什么 | 产物 | 你的动作 |
|---|---|---|---|
| 1 | 装 Docker + Harbor + uv；写 `preflight.py`；用 Seed 跑通 hello-world；跑通 `oracle` agent | 环境可用；版本号写进 `experiments/README.md` | 租机、给 key |
| 2 | 选 30–40 题（按 TB 类别分层，见下）；**E0 oracle 全跑**剔除环境坏题 + **`harbor check` 跑题目清单**（官方口径题目质量报告）；**E1 基线 k=3 过夜** + **噪声底**（10 题 k=5 两个种子）；同时写 `adapters/harbor.py` 和规则层 | 基线数字、噪声底 Δ、adapter 单测、题目质量报告 | — |
| 3 | 规则标签第一版；判官提示词（归因 + TB 十类动作编码 + 指令清晰度 0–3）；把 taxonomy 导出成 rubric 跑 **`harbor analyze --failing`** 当判官 #2；起 E2 强模型基线 k=2 | 每条 trial 一份 `labels.json`；两个判官的输出 | 一起看 5 条轨迹校对规则 |
| 4 | **你人工标 50–80 条**（在 `harbor view` 里读轨迹，标签写入同一 schema）；算判官 vs 人工 κ、两家判官互查、`harbor analyze` 判官一致率、判官不变性测试；定稿 `taxonomy.md`；**定稿 `HYPOTHESES.md`** | κ 数字；预注册文件 commit | 2–3 小时标注 |
| 5–6 | 实现第一批开关：`verifier_gate`（三档）、`adaptive_wait`、`task_contract`、`budget_hint`、`stuck_reminder`、`exit_code_prompt`；金标测试"全关 == 上游" | 每个开关一个 PR-sized 提交 + 单测 | — |
| 7 | **E4 消融过夜**：每开关单独开 k=3；**E5 成本匹配基线**；**E6 三臂独立性**；基线在同批次重跑 | 消融表 | — |
| 8 | `assumption_ledger`（若压缩会触发）、`read_file`（若基线 TRUNCATED_READ 率高）；**E8 改题再跑**（歧义报告前 5 题只改 instruction） | 第二批数字；题目质量 vs harness 效应分离 | — |
| 9 | **E3 Codex 同题基线**（配对 B）；**E7 两因子 2×2**；回归包 + 回归门脚本；blame 二维表计算 | 跨 harness 失败分布图；blame 表 | Codex 要 OpenAI key |
| 10 | 报告（四级指标、阶段面积图、终止阶段表、消融表按弱/强模型分列、拐杖标注、交接包）；仓库 README；给 Harbor 的 PR 草稿 | 报告 PDF / MD；仓库可复现 | 过一遍 |

最容易滑的：第 1 天（环境）、第 4 天（标注）。滑两天仍在两周内。

## 选题规则（第 2 天）

- 从 TB 2.x 按官方类别分层抽样，每类至少 2 题，共 30–40 题。
- **不按试跑结果选题**（均值回归，见 `decisions.md` D-013）。
- E0 oracle 在我们环境里挂掉的题：剔除并记录原因（环境问题 ≠ 模型能力）。
- 需要 GPU 或多容器（compose）的题跳过。
- 固定清单写入 `experiments/task_list.txt`，之后所有实验用同一份。

## 预算（粗估，按 trial 数）

| 实验 | trial 数 | 备注 |
|---|---|---|
| E0 oracle | 40 | 几乎不花模型钱 |
| E1 Seed 基线 k=3 + 噪声底 | 120 + 100 | 便宜模型 |
| E2 强模型基线 k=2 | 80 | 贵，是主要开销之一 |
| E3 Codex k=1–2 | 40–80 | OpenAI 计费 |
| E4 六个开关各 k=3 | 720 | 便宜模型 |
| E5 + E6 + E7 | 120 + 240 + 120 | 便宜模型 |
| E8 改题 | 30 | 便宜模型 |
| 判官调用 | 每条失败轨迹 2–3 次 | 另一家模型 |

便宜模型每 trial 大约 0.2–0.5 美元量级（取决于 Seed 定价，第 1 天核实后更新此表）。

## 风险与对策

| 风险 | 对策 |
|---|---|
| 国内网络拉不到镜像 | 境外节点；`preflight.py --pull-images` 预拉 |
| 方舟限流 / 超时被记成能力失败 | `exception_info` 类型化为 ENVIRONMENT，重试策略写进配置，不进能力统计 |
| Seed 窗口很大，压缩改动量不出 | 预注册里已声明 H4 条件；不做即可 |
| 30–40 题置信区间宽 | 报告只说"方向一致"；配对检验 + bootstrap 区间；噪声底先报 |
| 判官被措辞骗 | 不变性测试（第 4 天）；过早完成只用规则 |
| 改动之间互相干扰 | 每个开关独立；2×2 交互实验；confound 剔除规则写进 `HYPOTHESES.md` |
