# Terminal-Bench 2.1 任务质量审计（骨架，2026-09-24）

对象：本项目用的 41 道题。每题给出：题面清晰度评分（0 无问题 … 3 严重）、弱模型 Seed lite 通过率（E1 / E4 同批）、强模型 gpt-6-sol 通过率（E2，k=1）、失败的判官主标签、改题实验结果，以及一个**待人工确认**的缺陷类别。

缺陷类别定义（D-034）：**接口约定** = 题面没说但验收依赖的约定（地址基址、边界、信号语义、输出格式），改题面就能修；**领域知识** = 需要行业知识才能推断，题面提示也难救；**环境工具** = 验证器依赖的工具/版本环境里没有或不一致；**测试契约** = 题面与测试脚本的前提不一致；**无迹象** = 失败原因不在题面。

| 题 | 清晰度 意图/目标 | Seed E1 | Seed E4 | gpt-6-sol | 失败判官标签 | 改题实验 | 自动类别 | 状态 |
|---|---|---|---|---|---|---|---|---|
| adaptive-rejection-sampler | 1/2 | 1/3 | 1/3 | 1/1 | INSUFFICIENT_VERIFICATION×1, BUDGET_EXHAUSTED×1 | — | 疑似接口约定（次要） | 已验证 |
| cancel-async-tasks | 2/0 | 0/3 | 2/3 | 1/1 | INSUFFICIENT_VERIFICATION×2, SPEC_MISINTERPRETATION×1 | E8 3/3 | 接口约定 | 已验证 |
| chess-best-move | 2/0 | 0/3 | 2/3 | 1/1 | BUDGET_EXHAUSTED×2, SPEC_MISINTERPRETATION×1 | E8 2/3 | 无（能力） | 已验证 |
| configure-git-webserver | 1/1 | 2/3 | 2/3 | 1/1 | SPEC_MISINTERPRETATION×1 | — | 接口约定 / 测试契约 | 已验证 |
| count-dataset-tokens | 2/2 | 2/3 | 3/3 | 1/1 | BUDGET_EXHAUSTED×1 | — | 无（预算） | 已验证 |
| dna-insert | 2/1 | 1/3 | 1/3 | 1/1 | TASK_UNDERSPECIFIED×1, SPEC_MISINTERPRETATION×1 | E8 0/3; E8b 3/3 | 接口约定 + 环境工具 | 已验证 |
| extract-elf | 2/2 | 0/3 | 0/3 | 1/1 | SPEC_MISINTERPRETATION×2, TASK_UNDERSPECIFIED×1 | E8 3/3 | 接口约定 | 已验证 |
| headless-terminal | 2/0 | 2/3 | 3/3 | 1/1 | INSUFFICIENT_VERIFICATION×1 | — | 无（验证不足） | 已验证 |
| largest-eigenval | 1/1 | 1/3 | 3/3 | 1/1 | BUDGET_EXHAUSTED×1, CANNOT_JUDGE×1 | — | 环境工具（易抖动测试） | 已验证 |
| overfull-hbox | 0/0 | 1/3 | 2/3 | 1/1 | SPEC_MISINTERPRETATION×1, CANNOT_JUDGE×1 | — | 无（验证不足） | 已验证 |
| path-tracing-reverse | 0/0 | 0/3 | 0/3 | 1/1 | BUDGET_EXHAUSTED×3 | E8 0/3 | 无（预算/能力） | 已验证 |
| pytorch-model-cli | 3/2 | 2/3 | 2/3 | 1/1 | INSUFFICIENT_VERIFICATION×1 | — | 无（验证不足） | 已验证 |
| raman-fitting | 2/2 | 0/3 | 0/3 | 0/1 | SPEC_MISINTERPRETATION×3 | E8 0/3; E8b 0/3 | 领域知识 + 接口约定 | 已验证 |
| sanitize-git-repo | 2/2 | 2/3 | 1/3 | 1/1 | TASK_UNDERSPECIFIED×1 | — | 测试契约 | 已验证 |
| sqlite-with-gcov | 1/1 | 2/3 | 2/3 | 1/1 | SPEC_MISINTERPRETATION×1 | — | 无（验证不足） | 已验证 |
| build-pmars | 2/2 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| cobol-modernization | 0/0 | 2/3 | 3/3 | 1/1 | BUDGET_EXHAUSTED×1 | — | 无迹象（强模型能推断） | — |
| code-from-image | 0/0 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| constraints-scheduling | 1/0 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| fix-code-vulnerability | 2/2 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| fix-git | 2/2 | 3/3 | 3/3 | 1/1 | — | — | 无迹象 | — |
| gcode-to-text | 0/0 | 0/3 | 0/3 | 0/1 | BUDGET_EXHAUSTED×1, INSUFFICIENT_VERIFICATION×1, CAPABILITY×1 | — | 无迹象 | — |
| git-leak-recovery | 1/1 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| git-multibranch | 0/0 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| hf-model-inference | 1/0 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| kv-store-grpc | 1/1 | 2/3 | 2/3 | 1/1 | SPEC_MISINTERPRETATION×1 | — | 无迹象（强模型能推断） | — |
| large-scale-text-editing | 0/1 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| llm-inference-batching-scheduler | 1/1 | 2/3 | 2/3 | 1/1 | SPEC_MISINTERPRETATION×1 | — | 无迹象（强模型能推断） | — |
| log-summary-date-ranges | 1/1 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| merge-diff-arc-agi-task | 1/0 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| mteb-retrieve | 0/1 | 2/3 | 2/3 | 1/1 | SPEC_MISINTERPRETATION×1 | — | 无迹象（强模型能推断） | — |
| nginx-request-logging | 0/1 | 3/3 | 3/3 | 1/1 | — | — | 无迹象 | — |
| openssl-selfsigned-cert | 0/0 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| polyglot-c-py | 1/1 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| prove-plus-comm | 0/0 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| pypi-server | 1/1 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| query-optimize | 1/0 | 0/3 | 0/3 | 1/1 | INSUFFICIENT_VERIFICATION×2, CAPABILITY×1 | — | 无迹象（强模型能推断） | — |
| regex-log | 0/0 | 3/3 | 3/3 | 1/1 | — | — | 无迹象 | — |
| sqlite-db-truncate | 1/1 | 3/3 | 3/3 | 1/1 | — | — | 无迹象 | — |
| tune-mjcf | 1/0 | 3/3 |  | 1/1 | — | — | 无迹象 | — |
| vulnerable-secret | 0/2 | 3/3 | 3/3 |  | — | — | 无迹象 | — |

## 逐题证据

### adaptive-rejection-sampler
- 自动类别：**疑似接口约定（次要）**（已验证）
- 证据：人工定案：验证不足为主（自测 5000 样本未计时）；v3 判官指出评分超时时长题面未说，记次因。改题可加“评分时限”一句
- 清晰度判官认为缺：domain representation, whether density_function returns density or log-density, sample return format/type, default value for n
- 人工判断：（待填）

### cancel-async-tasks
- 自动类别：**接口约定**（已验证）
- 证据：取消语义（已启动的取消、排队的不启动、finally 自身会 await）题面未说；写明后 2/6 → 3/3
- 清晰度判官认为缺：whether to cancel active tasks or let them finish on interruption, whether to wait for cleanup before propagating the interrupt, how task exceptions are handled
- 已有改写：`experiments/e8_rewrites/cancel-async-tasks/instruction.md`
- 人工判断：（待填）

### chess-best-move
- 自动类别：**无（能力）**（已验证）
- 证据：写明“best = 一步将死、可多解”后仍 2/3，失败都是看图认子
- 清晰度判官认为缺：definition of “best” (such as engine evaluation or winning outcome)
- 已有改写：`experiments/e8_rewrites/chess-best-move/instruction.md`
- 人工判断：（待填）

### configure-git-webserver
- 自动类别：**接口约定 / 测试契约**（已验证）
- 证据：题面说“登录不用你管”，verify.sh 却要求存在 user 账号并可 ssh；模型据此没建账号 → clone 失败 404
- 清晰度判官认为缺：web-server implementation and document-root path
- 人工判断：（待填）

### count-dataset-tokens
- 自动类别：**无（预算）**（已验证）
- 证据：人工定案 BUDGET_EXHAUSTED：有候选计数却没先写答案文件；交付检查点针对的正是这类
- 清晰度判官认为缺：what “deepseek tokens” refers to, which science-domain text fields to count, how to handle chat formatting and special tokens
- 人工判断：（待填）

### dna-insert
- 自动类别：**接口约定 + 环境工具**（已验证）
- 证据：插入边界有两种等价切法、验证器用靠左的；环境未装 oligotm，apt 版本与验证器版本对同一序列判定相反；两者补齐后 3/3
- 清晰度判官认为缺：rules defining which primer architectures or rounds count toward the minimum number of pairs, FASTA header convention
- 已有改写：`experiments/e8_rewrites/dna-insert/instruction.md`
- 人工判断：（待填）

### extract-elf
- 自动类别：**接口约定**（已验证）
- 证据：题面示例地址 4194304 与参考实现（用段头 sh_addr、不加 PIE 偏移）对给定的 PIE 文件矛盾；写明约定后 0/6 → 3/3
- 清晰度判官认为缺：which memory regions to extract, whether to include BSS, value width and byte order, virtual or physical addresses
- 已有改写：`experiments/e8_rewrites/extract-elf/instruction.md`
- 人工判断：（待填）

### headless-terminal
- 自动类别：**无（验证不足）**（已验证）
- 证据：人工定案：只用 python REPL 测交互程序，题面明说要支持交互程序；pyte 处理私有转义序列有 bug 记次因
- 清晰度判官认为缺：definition of “supports interactive programs,” terminal dimensions/TERM requirements, lifecycle and output-reading semantics beyond the referenced interface
- 人工判断：（待填）

### largest-eigenval
- 自动类别：**环境工具（易抖动测试）**（已验证）
- 证据：速度测试逐尺寸起子进程跑 100 次取中位数、单次无重试；模型实现 5×5/7×7 为 24/25 µs，6×6 突跳 59 µs（参考 43）→ 那一刻 CPU 被抢；建议测试改为多轮取最优或重试
- 清晰度判官认为缺：required return format, precise performance comparison protocol
- 人工判断：（待填）

### overfull-hbox
- 自动类别：**无（验证不足）**（已验证）
- 证据：规则清楚；重放改动用测试逐词检查：#1 违规是介词 in→at（模型的修复 sed 未命中、未验证），#2 是冠词 an→a；两家判官指控的“不合法同义词”经核对全在表里
- 人工判断：（待填）

### path-tracing-reverse
- 自动类别：**无（预算/能力）**（已验证）
- 证据：对照题，题面清楚，6/6 失败全是 BUDGET_EXHAUSTED
- 人工判断：（待填）

### pytorch-model-cli
- 自动类别：**无（验证不足）**（已验证）
- 证据：三家判官一致 INSUFFICIENT_VERIFICATION；v3 另指出预处理把 PNG alpha 通道算进灰度（bug），属能力/验证
- 清晰度判官认为缺：model architecture and source/training of weights, image preprocessing requirements, weights.json schema, prediction.txt path relative to /app
- 人工判断：（待填）

### raman-fitting
- 自动类别：**领域知识 + 接口约定**（已验证）
- 证据：x 轴需 1e7/x 换算（领域知识，题面提示不够）；给了换算后峰位全对，仍卡在题面未给的 2D 拟合窗口（E8b 0/3）
- 清晰度判官认为缺：peak-fitting model, input file path and format, definition of gamma
- 已有改写：`experiments/e8_rewrites/raman-fitting/instruction.md`
- 人工判断：（待填）

### sanitize-git-repo
- 自动类别：**测试契约**（已验证）
- 证据：测试写死原始提交 SHA 做 diff；题面“确保仓库里没有敏感值”合理导向重写历史，重写 + gc 后 SHA 消失
- 清晰度判官认为缺：which credential types count beyond the examples, whether Git history is in scope, repository path
- 人工判断：（待填）

### sqlite-with-gcov
- 自动类别：**无（验证不足）**（已验证）
- 证据：“放到 PATH 里”清楚；模型把 PATH 写进 profile.d/.bashrc 对子进程无效，自检在同一 shell 里 export 后 which，等于没查
- 清晰度判官认为缺：explicit executable name and install path
- 人工判断：（待填）

### mteb-retrieve
- 自动类别：**无迹象（强模型能推断）**（—）
- 证据：tie-breaking rule for documents with equal cosine similarity
- 清晰度判官认为缺：tie-breaking rule for documents with equal cosine similarity
- 人工判断：（待填）

### query-optimize
- 自动类别：**无迹象（强模型能推断）**（—）
- 证据：performance metric or benchmark for “as efficient as possible”
- 清晰度判官认为缺：performance metric or benchmark for “as efficient as possible”
- 人工判断：（待填）

