# 实验清单

钉死的版本（2026-09-23 第 1 天）：
- 服务器：Hetzner CPX62，Ashburn，Ubuntu 24.04.4 LTS，x86_64，16 vCPU / 30 GB / 338 GB 可用
- Docker 29.8.1；uv 0.12.18
- Harbor **0.23.0**（`uv tool install harbor`）；源码克隆在 `/root/work/harbor`，commit `15da91c1`（2026-09-22），用于读 Terminus 2 源码、金标测试与示例任务
- 数据集：`terminal-bench/terminal-bench-2-1`（Harbor Hub 注册名，`@latest`，89 题），缓存在 `/root/.cache/harbor`
- 冒烟：`harbor run -p /root/work/harbor/examples/tasks/hello-world -a oracle` → reward 1.0，26 s（`/root/work/jobs/smoke-hello`）
- Seed：被测 `doubao-seed-2-1-lite-260915`（输入 0.8 / 输出 2.7 元/百万 token），强模型 `doubao-seed-2-1-pro-260915`（6 / 30）；窗口 1024k；限流 lite 5000k TPM / 30k RPM（8 并发够用），pro 1000k TPM / 500 RPM（**pro 基线并发 ≤3**）；OpenAI key 已就位（2026-09-23），可用模型（新→旧）：gpt-6-sol / gpt-6-luna（09-14）、gpt-6-astra（08-27）、gpt-5.6-terra / sol / luna（06-23）、gpt-5.5、gpt-5.4 / mini / nano、gpt-5.3-codex…；判官模型 ____（定价核对后定）；Codex 版本 ____
- 工作目录：`/root/work/agent_harness`（本地 `agent_harness/` 用 rsync 同步）；jobs 输出 `/root/work/jobs`

所有实验共用 `task_list.txt`（第 2 天定，之后不改）。每个配置文件顶部注释写清对应 `HYPOTHESES.md` 的编号。

| 编号 | 目的 | 配置 | 并发 / k | 产物 |
|---|---|---|---|---|
| E0 | oracle 检查，剔除环境坏题 | `configs/e0_oracle.resolved.yaml` | 8 / 1 | **已跑 2026-09-23**：56 题 53 过，19m39s；3 题剔除（`task_list_excluded.txt`，均为 verifier 问题）；主清单 41 题定稿 |
| E1 | Seed 基线 | `configs/e1_baseline_seed.yaml` | 8 / 3 | **已跑 2026-09-23**：123 条 2h04m，19.1 元；trial 级 68.3%，pass@3 82.9%；16 条 AgentTimeout；失败规则分布 PREMATURE_COMPLETION 64% / BUDGET_EXHAUSTED 36% / TRUNCATED_READ 28% / COMMAND_NOT_FOUND 23% / POLLING 8% / STUCK_AT_PROMPT 3%；报告 `/root/work/reports/e1-baseline-seed/`。**注意**：第一次 E1 因方舟欠费中断（`jobs/e1-baseline-seed-ABORTED-overdue`，作废）。**冒烟 2026-09-23**：fix-git / regex-log / nginx-request-logging 3/3 过，2m45s，每题 3–9 轮、0.9–3.4 万输入 token、≈0.03 元，缓存命中 0–34% |
| E1n | 噪声底：10 题 k=5，两个种子 | `configs/e1n_noise_floor.yaml`（跑两次，改 `job_name` 后缀 s1/s2） | 8 / 5 | **已跑 2026-09-23**：s1 60.0%（6 超时）vs s2 68.0%（5 超时），各 53 min；δ = 8 pp；k=3 子样本中位 6.7 pp；cancel-async-tasks 0.4→0.6、query-optimize 0→0.2（E1 的"三次全挂"部分是运气） |
| E2 | 强模型基线（配对 A） | `configs/e2_baseline_strong.yaml` | 4 / 1 | **已跑 2026-09-23**：gpt-6-sol 41 题 k=1，25m56s，$3.45；端到端 92.7%（reward-only 95.0%，1 条 agent_error）；平均 10.7 轮、缓存命中 90.3%。配对 A（vs E1）：**+27.5 pp** [+16.7, +39.2]，超时 16→0，弱模型的 BUDGET_EXHAUSTED / POLLING / COMMAND_NOT_FOUND 在强模型上归零；报告 `/root/work/reports/{e2-baseline-strong,compare-e1-e2}` |
| E3 | Codex 同题基线（配对 B），需同一 GPT-5.x 也在 Terminus 2 上跑 k=2 | `configs/e3_codex.yaml`、`configs/e3_terminus_gpt.yaml` | 4 / 2 | |
| E4 | 消融：每个开关单独开 | `configs/e4-*.resolved.yaml`（`resolve.py --agent terminus2_patches.agent:Terminus2Patched --set ...`） | 6 / 3 | **题集 `task_list_ablation.txt`：E1 非全过的 21 题 + 5 道 3/3 锚题 = 26 题**（钱只够这样；D-013 同批次基线重跑 `e4-baseline-rerun` 抵消选题偏差）。六臂：baseline-rerun / contract（task_contract+assumption_ledger）/ auditor / selfcheck / hygiene（stuck_reminder+budget_hint+exit_code_prompt）/ adaptive-wait。2026-09-23 晚串行启动，tmux `e4` |
| E5 | 成本匹配基线（H1c） | `configs/e5_cost_matched.yaml` | 8 / 3 | |
| E6 | 三臂独立性（H1b） | `configs/e6_gate_self_check.yaml` + E4 的 auditor 臂 + E4 基线 | 8 / 3 | |
| E7 | 2×2 交互（H9） | `configs/e7_factorial.yaml` | 8 / 3 | |
| E8 | 改题不改 harness（H11） | `configs/e8_rewrite_seed.yaml`，`datasets: - path: /root/work/tasks_e8`（`build_e8_dataset.sh` 从 harbor 缓存复制 6 题并覆盖 `e8_rewrites/*/instruction.md`） | 6 / 3 | 完成 2026-09-24：trial 级 44.4%，见下表 |
| E9 | 回归包 | `regression_tasks.txt`（锚题 = E1 与 E4 基线都 3/3；目标题 = 都 0/3）+ `agenteval regress A B --tasks ...`（锚题跌 > 34 pp 或目标题回到 0 → 退出码 1） | 1 / 1 | 已可用 |

命令形式（2026-09-23 核对，Harbor 0.23.0）：

```bash
# 1) 生成正式配置（自动加题名前缀；上游 terminus-2 时自动去掉我们的开关）
python3 experiments/resolve.py experiments/configs/e1_baseline_seed.yaml --tasks experiments/task_list.txt --job e1-baseline-seed --k 3 --concurrency 8

# 2) 在服务器 tmux 里跑。Terminus 2 在宿主机进程里走 LiteLLM 的 openai/ 提供方，读 OPENAI_API_KEY，所以把方舟 key 映射过去
tmux new -d -s e1 'source ~/.secrets.env; export OPENAI_API_KEY=$ARK_API_KEY PATH=$HOME/.local/bin:$PATH NO_COLOR=1; \
  harbor run -c /root/work/agent_harness/experiments/configs/e1-baseline-seed.resolved.yaml --ae OPENAI_API_KEY=$ARK_API_KEY -y > /root/work/jobs/e1.log 2>&1'

# 3) 分析
agenteval analyze /root/work/jobs/e1-baseline-seed --out reports/e1
```

fork agent 的用法（2026-09-23 核对）：`-a terminus2_patches.agent:Terminus2Patched --ak verifier_gate=auditor`，需要 `PYTHONPATH=/root/work/agent_harness` 且用 `.venv/bin/harbor`（装了 harbor==0.23.0 + 本包）；`resolve.py --agent terminus2_patches.agent:Terminus2Patched --set verifier_gate=auditor` 会生成对应配置。

已知提醒：LiteLLM 对自定义模型不知道缓存价，`model_info` 里要补 `cache_read_input_token_cost`（方舟前缀缓存的命中价，待查）；方舟返回 `prompt_tokens_details.cached_tokens`，Harbor 记为 `n_cache_tokens`。Seed 默认开思考模式（`reasoning_tokens` 计入输出 token 计费）。


| 附 | rubric 提炼 + 偏序验证（E2 强 × E1 弱） | `agenteval rubric` | — | **已跑 2026-09-23**：19 题有配对，76 条 rubric，69 条通过偏序验证（强侧 k=1，验证偏松，报告注明）；`/root/work/reports/rubric/e2_vs_e1.json` |


### E4 结果（2026-09-24，26 题 × k=3，同批次基线重跑；预注册门槛 δ = 8 pp）

| 臂 | 开关 | trial 级通过率 | Δ 题级配对 | 95% 区间 | 模糊题 Δ / 清晰题 Δ | 超时 | 轮数 | 输入 token/trial | 成本/trial | 判定 |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline-rerun | 全关（fork） | 61.5% | — | — | — | 10 | 14.4 | 227.6k | 0.184 | 参照 |
| contract | task_contract + assumption_ledger | 69.2% | **+7.7** | [-1.3, +17.9] | **+13.9 / +2.4** | 14 | 13.8 | 223.1k | 0.197 (+7%) | 不确定（< δ，区间跨零）；方向与 H3 预测一致 |
| selfcheck | verifier_gate=self_check | 67.9% | +6.4 | [-2.6, +15.4] | +8.3 / +4.8 | 14 | 16.8 | 323.4k | 0.249 (+35%) | 不确定 |
| auditor | verifier_gate=auditor | 61.5% | +0.0 | [-11.5, +10.3] | -2.8 / +2.4 | **17** | 16.4 | 316.1k | 0.237 (+29%) | 无效：89 次审计、22 次打回，打回的时间把 7 条推到超时 → H1 证伪（Seed lite 上）、H1b 反向（self_check ≥ auditor） |
| hygiene | stuck_reminder + budget_hint + exit_code_prompt | 60.3% | -1.3 | [-12.8, +10.3] | +2.8 / -4.8 | 12 | 14.0 | 187.8k (-17%) | 0.175 (-5%) | 无效；stuck_reminder 一次都没触发（H6 无数据） |
| adaptive-wait（78/78，补跑 5 条后） | adaptive_wait | 59.0% | -2.6 | [-14.1, +9.0] | -5.6 / +0.0 | 12 | 13.7 | 201.8k (-11%) | 0.187 (+2%) | 通过率无效；空等待轮 -27%/trial、轮数 -0.6、token -11%；1494+ 条命令里哨兵正常返回 ~70%、识别到交互提示 65 次 |

读法：所有 Δ 都在噪声底 δ=8 pp 之内、区间都跨零 → 通过率上**没有一个改动能说"有效"**；能说的是方向与结构：契约把收益集中在模糊题（+13.9 vs +2.4），auditor 的独立性没换来准确率只换来 +29% 成本和更多超时，self_check 更便宜且不差。

补充读数（同批次六臂）：
- **H2（adaptive_wait）**：空等待轮 35→24（每 trial 0.45→0.33，−27%，未达预注册的 −50%）；失败里 POLLING 占比 13.3%→3.6%、TRUNCATED_READ 33%→14%；轮数 −1.0、输入 token −16%、墙钟 +4%（哨兵等待累计 6215 s / 73 trial ≈ 85 s/trial，把原来分摊在多轮的等待集中到了一轮里）。
- **contract 的解析错误轮 8→52**：不是模型格式变差，是首轮只读打回走的是上游"parsing errors"重提示路径（42 次），adapter 把它计成 parse_error；报告里要区分"打回"和"真解析错"。
- **hygiene**：stuck_reminder 一次都没触发（连续 5 次相同命令在 26 题里没出现过）；缓存命中 29%→19% 与预算提示无关（提示追加在末尾），更像方舟缓存的批次差异，噪声。
- **auditor 的机制观察**：89 次审计、22 次打回（25%）；打回后模型平均多用 2 轮，7 条因此撞到 15 分钟时限。打回本身是"对"的（判官把它们判为 incomplete/unknown），但对 Seed lite 来说"知道不完整"和"能补完"之间有差距 → 这是模型侧的残差，进交接包。

**E8 改题重跑（2026-09-24，Seed lite，k=3；改写文本 `e8_rewrites/`，原则 D-032）：**

| 题 | E1 基线 | E4 同批基线 | 改题后 | 读法 |
|---|---|---|---|---|
| extract-elf | 0/3 | 0/3 | **3/3** | 补上“地址 = 段头 sh_addr、不加 PIE 偏移、4 字节小端、要能跑在别的二进制上”后全过 → 题面示例地址误导是真的 |
| cancel-async-tasks | 0/3 | 2/3 | 3/3 | 写明取消语义后 3/3，但基线本身 2/3，提升在噪声内 |
| chess-best-move | 0/3 | 2/3 | 2/3 | 无变化；失败原因是看图认子（能力） |
| raman-fitting | 0/3 | 0/3 | 0/3 | 提示“可能要换算”不够，模型把最强的峰线性映射到 1580/2680；缺的是 1e7/x 这条领域知识 |
| dna-insert | 1/3 | 1/3 | 0/3 | 边界约定仍没写清；另发现环境没装 oligotm，apt 装的版本与验证器版本对同一序列给出 58.04 vs 55.86 度 → ENVIRONMENT |
| path-tracing-reverse（对照，未改） | 0/3 | 0/3 | 0/3 | 三次都是 BUDGET_EXHAUSTED，如预期 |

**E4t 模糊题补跑（2026-09-24，14 道 clarity ≥ 2 的题，基线 / 契约各 k=3，同批）+ 与 E4 合并：**

| 口径 | 基线 | 契约 | Δ 题级配对 | 95% 区间 |
|---|---|---|---|---|
| E4 首批模糊题子集（12 题 × 3） | — | — | +13.9 | — |
| E4t 补跑单独（14 题 × 3） | 65.9% | 69.0% | +3.6 | [−8.3, +20.2] |
| 合并（14 题，每题最多 6 次） | 62.3% | 70.5% | **+6.7** | [−5.2, +21.4] |

逐题（合并后基线 → 契约）：extract-elf 0 → 0.83 是唯一大幅变化；sanitize-git-repo 0.33 → 0.67、adaptive-rejection-sampler 0.5 → 0.67 小涨；build-pmars 1.0 → 0.67、count-dataset-tokens 1.0 → 0.83 小跌；其余持平。契约臂轮数 −3.1、成本 −26%（首轮打回 30 次，但整体更早收敛）。

**E4p 契约加样与 v2（2026-09-26，41 题 × k=3，三臂并行）：**

| 口径 | 基线 | v1 | v2 |
|---|---|---|---|
| 全集 | 76.4% | 74.0%（−2.4 [−8.9, +4.1]） | 76.4%（+0.0 [−9.8, +8.9]） |
| 模糊题 14 道 | 61.9% | 69.0%（+7.1） | 71.4%（+9.5） |
| 清晰题 27 道 | 84.0% | 76.5%（−7.4） | 79.0%（−4.9） |
| 成本/trial | 0.157 | 0.162 | 0.161 |
| 超时 | 13 | 16 | 14 |

合并 E4+E4t+E4p 的模糊题（每题 ≥6 次，n=119/120）：62.2% → 70.0%，Δ **+7.6 [−0.0, +17.2]**。
账本命中决定性细节：v1、v2 都是 12/15 = 80%；但命中时通过率 v1 8/12、**v2 3/12**（强制逐点 resolutions 反而干扰决策）。v2 的 resolutions 字段 15/15 都写了。
→ D-048：契约是条件式手段；H17 做“只在模糊题启用”。（**已被 D-050 撤回**，见下方 H17）

**H17 条件式契约（2026-09-26，41 题 × k=3，基线 / 条件式同时启动、并发 6 + 6，35.1 元；配置 `configs/h17-*.resolved.yaml`，分析 `tools/h17_report.py` → `reports/h17/report.md`）：**
开关（D-049）：开跑前 harness 单独调一次 Seed 给题面打清晰度分（clarity_v1），任一维 ≥2 才用契约模板，否则整道题走上游。离线预检三种开关：预注册的“首轮列出模糊点”在清晰题 96% 都会开（失效）；首轮自评 79% / 43%；开跑前评分 90% / 27%（采用）。

| 口径 | 基线 | 条件式 | Δ [95% CI] | 超时 |
|---|---|---|---|---|
| 全集 41 | 76.4% | 76.4% | +0.0 [−6.5, +6.5] | 12 → 15 |
| 模糊题 14 | 66.7% | 61.9% | −4.8 [−21.4, +11.9] | 3 → 6 |
| 清晰题 27 | 81.5% | 84.0% | +2.5 [−2.5, +7.4] | 9 → 9 |

开关实跑：模糊题开 36/42、清晰题误开 24/81；评分耗时中位 48 s；评分超时 1 次。判定不成立（模糊题收益消失）。
复现检查（`tools/h17_pool.py`、`tools/h17_clear.py`）：契约 v1 在模糊题逐批 +13.9 / +4.8 / +7.1 / −4.8，四批合并 **+4.8 [−3.0, +13.1]**；在 H17 被误开契约的 9 道清晰题上 **+3.7 [+0.0, +9.3]**（E4p 是 −7.4）。→ D-050：契约的子集效应没有复现，D-048 撤回。
注：条件式臂比基线臂晚结束约 20 个 trial，末段在较轻负载下单独运行（两臂同秒启动、并发相同）。

**E4v2 第二圈（2026-09-26，26 题 × k=3，三臂**并行**，D-040）：**

| 臂 | trial 级通过率 | Δ 题级配对 | 95% 区间 | 超时 | 轮数 | 成本/trial | 失败且无交付 | 机制统计 |
|---|---|---|---|---|---|---|---|---|
| baseline | 65.4% | — | — | 9 | 15.9 | 0.228 | 11 | — |
| deliverable_checkpoint | 60.3% | −5.1 | [−15.4, +3.8] | 8 | 14.0 | 0.189 (−17%) | **6** | 检查 51 次 / 发现缺失 14 次 |
| grader_check | 59.0% | −6.4 | [−19.2, +6.4] | **34** | **43.3** | 0.479 (+110%) | 8 | — |

第五对同配置噪声：E4 基线 61.5% → E4v2 基线 65.4%，Δ +3.8 [−7.7, +14.1]（前四对：+11.5、+1.4、+13.1、本对）。噪声底的估计写成分布：题级 Δ 的绝对值中位数约 4–11 pp。

**E8b（把 E8 里仍失败的两道补到底，泄露式，只用于归因）：** dna-insert 3/3（题面写明验证器的边界规则，oligotm 与验证器同源安装）；raman-fitting 0/3（给了 1e7/x 后 G 峰全对、2D 峰位对，卡在 2D 的 offset/gamma——三次拟合窗口都与出题人不同，题面未给窗口）。

**契约账本命中率（E4 + E4t 契约臂，人工定案为“题目没说清”的五道题）：** 账本点到决定性细节 → 通过 12/19（63%）；没点到 → 3/8（38%）；同组基线 ≈ 35%。逐题：extract-elf 点到 4/4 过、没点到 1/2；sanitize-git-repo 点到 4/6；cancel-async 点到 3/6；configure-git-webserver 点到 1/3；dna-insert 从未点到（2/6）。→ H15 契约 v2。

**E4s 强模型拐杖判定（gpt-6-sol，同 26 题，k=2；2026-09-24）：**

| 臂 | 可评 trial | 通过率 | Δ题级配对 | 95% 区间 | 轮数 | $/trial | 判定 |
|---|---|---|---|---|---|---|---|
| baseline | 50 | 88.0% | — | — | 11.6 | 0.101 | 参照 |
| contract | 46（4 条 setup_failed，环境） | 87.0% | +0.0 | [−12.0, +12.0] | 13.2 | 0.159 (+57%) | 拐杖：弱模型 +7.7，强模型 0 |
| self_check | 45（5 条 setup_failed，1 超时） | 86.7% | −2.1 | [−12.5, +8.3] | 20.5 | 0.181 (+79%) | 有害：轮数翻倍、通过率不动 |

setup_failed 是 docker 环境起不来（与 agent 无关），已从能力可评集合排除；`harbor` 原始 Mean（把它们算失败）分别是 84.6 / 76.9 / 75.0，所以看拐杖判定要用可评口径。

**E4 六臂失败归因（判官 gpt-6-sol，只判失败 trial；2026-09-24）：**

| 判官主标签 | baseline-rerun | contract | selfcheck | auditor | hygiene | adaptive-wait |
|---|---|---|---|---|---|---|
| SPEC_MISINTERPRETATION | 13 | **9** | 10 | 12 | 9 | 16 |
| BUDGET_EXHAUSTED | 6 | 7 | 5 | 8 | 7 | 5 |
| INSUFFICIENT_VERIFICATION | 5 | 3 | 4 | 5 | 6 | 3 |
| TASK_UNDERSPECIFIED | 2 | 1 | 2 | 4 | 3 | 1 |
| CAPABILITY | 1 | 3 | 2 | 0 | 3 | 3 |
| CANNOT_JUDGE | 2 | 1 | 1 | 0 | 2 | 0 |
| ACKNOWLEDGED_BUT_IGNORED / PREMATURE_COMPLETION / GOAL_DRIFT | 1 | 0 | 1 | 1 | 1 | 0 |
| 失败总数 | 30 | 24 | 25 | 30 | 31 | 28 |

读法：契约臂 SPEC_MISINTERPRETATION 13→9、INSUFFICIENT_VERIFICATION 5→3，减少的失败正好落在 H3 预测的那一类上（机制→失败类对应成立）；
self_check 对 INSUFFICIENT_VERIFICATION 只从 5 减到 4，它的 +6.4 pp 更像是"多一轮机会"而不是"真的去验证了"；auditor 一条 INSUFFICIENT_VERIFICATION 都没减掉但 BUDGET_EXHAUSTED 6→8，与"打回把 trial 推到超时"一致。
数字都在个位数，只能当方向读，不能当证据。

**SWE-bench Verified 冒烟（2026-09-26，20 题按难度分层、k=1，baseline / adaptive_wait 同时启动、并发 3 + 3，共 12.3 元；清单 `task_list_swev_smoke.txt`，配置 `configs/swev-smoke-*.resolved.yaml`）：**

| 臂 | 通过 | 按难度（<15 min / 15 min–1 h / 1–4 h） | 超时 | 平均用时 | 总花费 | 平均读入 token |
|---|---|---|---|---|---|---|
| baseline | 15/20（75%） | 6/7、6/9、3/4 | 0 | 14 分钟 | 6.84 元 | 493k |
| adaptive_wait | 15/20（75%） | 6/7、6/9、3/4 | 0 | 9 分钟 | 5.42 元 | 412k |

两臂挂的是同样 5 道（django-10097、django-14170、sympy-18199、sympy-20438、sympy-21930）。adaptive_wait 按题配对：用时 −32% [−51%, +4%]、花费 −21% [−48%, +30%]；基线 ≥15 分钟的 7 道题合计 199 → 96 分钟。方向与 TB 上的效率收益一致，但每题 1 次、20 题，区间跨零。
判定：Seed lite 在 SWE-bench Verified 上基线 75%，高于预设的 30–60% 区间，失败集两臂相同 → 这里同样没有给 harness 提分的余地，不在此做“加工具”正式实验。

**SWE-bench Pro 冒烟（2026-09-26，10 题、每个仓库一道，k=1，只跑基线；清单 `task_list_swepro_smoke.txt`）：** 有效 10 次中通过 **9 次**（唯一失败 ansible）；平均 19–31 分钟、每次 0.2–1.9 元，合计约 9 元。另有 3 次环境故障（element-web、tutanota、qutebrowser：镜像 tmux 低于 3.2，不认 `--ae` 带来的 `-e` 选项，见 D-051），去掉 `--ae` 后重跑三题全部通过，故障那 3 次不计。
核查：镜像里保留了远程分支，比题目起点新的提交抽查为 631（vuls）、793（openlibrary）、24,328（protonmail），`git log --all` 即可能看到官方修复；但 10 次轨迹里模型只看过起点以前的历史（openlibrary 那次 `git show 91831753a` 经 `merge-base --is-ancestor` 确认是过去的提交），未利用。题面附带逐条需求与接口说明（config 字段 `requirements`、`interface`），是 Seed lite 分数高的主要原因。
判定：基线 90%，高于 20–50% 区间，同样没有给 harness 提分的余地。

**TB 4.0 冒烟（2026-09-26，54 道可跑题中随机 10 道，k=1，只跑基线；清单 `task_list_tb4_smoke.txt`）：** **0/10**，合计 32.4 元，平均 73 分钟、70 轮；5 道跑满 `max_turns=100`（biped-contact-dynamics 185 分钟、8.9 元）。注意：TB4 每题设计时限 8 小时，前沿 agent 一次要跑上千轮；我们的 100 轮上限在一半题上是实际约束，所以 0/10 的含义是“Seed lite + 100 轮预算下做不出来”，不是“无限预算也做不出来”。

**三个基准冒烟汇总（2026-09-26，共约 54 元）：** SWE-bench Verified 75%（15/20）、SWE-bench Pro 90%（9/10）、TB 4.0 0%（0/10）。没有一个落在能测出 harness 提分的 20–50% 区间：代码修复类题目 Seed lite 已经很强（题面给得越全越强，Pro 附带需求与接口说明），前沿终端题在 100 轮预算下又完全做不出来。按事先约定，停止“换基准找 harness 提分”这条线。
