# 接受门回测：历史上做过的成对实验

## 改动 vs 基线

| 对比 | 题数 | trial（基线/候选） | 同时跑 | 通过率 Δ（pp）[95% 区间] | 超时 Δ（pp） | 效率变化 | 门的决定 | 当时的人工结论 |
|---|---|---|---|---|---|---|---|---|
| E4 契约 | 26 | 78/78 | 否 | 7.7 [-1.3, 17.9] | 5.1 | turns -4%, tokens_in -2%, minutes +7% | **INCONCLUSIVE** | 不确定 +7.7 [−1.3, +17.9]；之后四批没复现 |
| E4 self_check | 26 | 78/78 | 否 | 6.4 [-2.6, 15.4] | 5.1 | turns +17%, tokens_in +42%, minutes +7% | **INCONCLUSIVE** | 不确定 +6.4 [−2.6, +15.4]；成本 +35% |
| E4 auditor | 26 | 78/78 | 否 | 0.0 [-11.5, 10.3] | 9.0 | turns +13%, tokens_in +39%, minutes +29% | **REJECT** | 退役：+0.0，超时 10→17，成本 +29% |
| E4 hygiene | 26 | 78/78 | 否 | -1.3 [-12.8, 10.3] | 2.6 | turns -3%, tokens_in -18%, minutes +6% | **INCONCLUSIVE** | 退役：−1.3 |
| E4 adaptive_wait | 26 | 78/78 | 否 | -2.6 [-14.1, 9.0] | 2.6 | turns -5%, tokens_in -11%, minutes +9% | **INCONCLUSIVE** | 只省资源：空等待轮 −27%、token −11% |
| E4t 契约（模糊题） | 14 | 42/42 | 否 | 3.6 [-8.3, 20.2] | -9.5 | turns -18%, tokens_in -33%, minutes -8% | **INVALID**（放宽次数要求后：INCONCLUSIVE） | +3.6 [−8.3, +20.2] |
| E4v2 交付检查点 | 26 | 78/78 | 是 | -5.1 [-15.4, 3.8] | -1.3 | turns -12%, tokens_in -22%, minutes -5% | **INCONCLUSIVE** | 机制成立，通过率 −5.1，成本 −17% |
| E4v2 grader_check | 26 | 78/78 | 是 | -6.4 [-19.2, 6.4] | 32.1 | turns +171%, tokens_in +298%, minutes +66% | **REJECT** | 有害：超时 9→34，成本 +110% |
| E4p 契约 v1 | 41 | 123/123 | 是 | -2.4 [-8.9, 4.1] | 2.4 | turns -7%, tokens_in +1%, minutes +5% | **INCONCLUSIVE** | 无效 −2.4 [−8.9, +4.1] |
| E4p 契约 v2 | 41 | 123/123 | 是 | 0.0 [-9.8, 8.9] | 0.8 | turns -5%, tokens_in -3%, minutes +14% | **REJECT** | 无效 +0.0 [−9.8, +8.9] |
| H17 条件式契约 | 41 | 123/123 | 是 | 0.0 [-6.5, 6.5] | 2.4 | turns -0%, tokens_in -10%, minutes +18% | **REJECT** | 预测证伪 +0.0 [−6.5, +6.5] |
| E4s 契约（gpt-6-sol，k=2） | 26 | 52/52 | 否 | —  | — | — | **INVALID** | 拐杖：+0.0，成本 +57% |
| E4s self_check（gpt-6-sol，k=2） | 26 | 52/52 | 否 | —  | — | — | **INVALID** | 有害：−2.1，轮数近翻倍 |
| Qwen H1 接口修补 | 30 | 120/120 | 是 | 5.0 [-5.0, 16.7] | 2.5 | turns -18%, tokens_in -41%, minutes +1% | **ACCEPT_EFFICIENCY** | +5.0 [−5.0, +16.7] 不显著；格式错误轮 −93% |
| Qwen H2 vs H0 | 30 | 120/120 | 是 | 5.8 [-5.0, 17.5] | 2.5 | turns -2%, tokens_in -1%, minutes +22% | **INCONCLUSIVE** | +5.8 [−5.0, +17.5] 不显著 |
| Qwen 交卷把关（H2 vs H1） | 30 | 120/120 | 是 | 0.8 [-4.2, 6.7] | 0.0 | turns +20%, tokens_in +67%, minutes +22% | **REJECT** | +0.8 [−4.2, +6.7]，预注册预测证伪 |
| 合成留出题 H2 vs H0（原版） | 37 | 111/111 | 是 | -0.9 [-5.4, 3.6] | 3.6 | turns -3%, tokens_in +8%, minutes +10% | **INCONCLUSIVE** | −0.9 不显著 |
| 合成留出题 H2 vs H0（SFT） | 37 | 111/111 | 是 | 2.7 [-3.6, 9.0] | 0.9 | turns -10%, tokens_in -8%, minutes -3% | **INCONCLUSIVE** | +2.7 不显著 |
| SWE-bench Verified adaptive_wait（k=1） | 20 | 20/20 | 是 | 0.0 [0.0, 0.0] | 0.0 | turns -7%, tokens_in -16%, minutes -32% | **INVALID**（放宽次数要求后：INCONCLUSIVE） | 通过相同；用时 −32% |

## 同配置空对照（两边配置相同：任何 ACCEPT 都是误收）

| 对比 | 题数 | trial（基线/候选） | 同时跑 | 通过率 Δ（pp）[95% 区间] | 超时 Δ（pp） | 效率变化 | 门的决定 | 当时的人工结论 |
|---|---|---|---|---|---|---|---|---|
| 空对照 E1 → E4 基线（隔 3 小时） | 26 | 78/78 | 否 | 11.5 [2.6, 21.8] | -6.4 | turns -10%, tokens_in -23%, minutes -4% | **PROVISIONAL** | D-040 记为批次漂移 +11.5 [+2.6, +21.8] |
| 空对照 E4 → E4v2 基线 | 26 | 78/78 | 否 | 3.8 [-7.7, 14.1] | -1.3 | turns +11%, tokens_in +32%, minutes +1% | **INCONCLUSIVE** | +3.8 [−7.7, +14.1] |
| 空对照 E4p → H17 基线（41 题） | 41 | 123/123 | 否 | 0.0 [-8.1, 7.3] | -0.8 | turns -9%, tokens_in -14%, minutes -4% | **INCONCLUSIVE** | 76.4% vs 76.4% |
| 空对照 Qwen H0 两批（k=2） | 30 | 60/60 | 否 | -1.7 [-11.7, 8.3] | 1.7 | turns -6%, tokens_in -10%, minutes -2% | **INVALID**（放宽次数要求后：INCONCLUSIVE） | −1.7 |
| 空对照 Qwen 原版 合成留出题（隔一天） | 37 | 111/111 | 否 | 2.7 [-0.9, 6.3] | -3.6 | turns +12%, tokens_in +26%, minutes -22% | **PROVISIONAL** | 14% vs 16% |
| 空对照 Qwen 原版 TB（隔一天） | 30 | 120/120 | 否 | 5.8 [-4.2, 17.5] | -4.2 | turns +0%, tokens_in +12%, minutes -20% | **PROVISIONAL** | — |
| 空对照 Qwen SFT 合成留出题（隔一天） | 37 | 111/111 | 否 | -2.7 [-9.0, 2.7] | -3.6 | turns +8%, tokens_in +22%, minutes -18% | **PROVISIONAL** | 16% vs 14% |

## 门给出的理由
- E4 契约：no reliable difference: pass +7.7 pp [-1.3, +17.9]; efficiency changes turns, tokens_in, minutes not significant
- E4 self_check：no reliable difference: pass +6.4 pp [-2.6, +15.4]; efficiency changes turns, tokens_in, minutes not significant
- E4 auditor：cost up without a pass-rate gain: minutes +29%
- E4 hygiene：no reliable difference: pass -1.3 pp [-12.8, +10.3]; efficiency changes turns, tokens_in, minutes not significant
- E4 adaptive_wait：no reliable difference: pass -2.6 pp [-14.1, +9.0]; efficiency changes turns, tokens_in, minutes not significant
- E4t 契约（模糊题）：baseline: 1 tasks have fewer than 3 usable attempts（放宽后：no reliable difference: pass +3.6 pp [-8.3, +20.2]; efficiency changes turns, tokens_in, minutes not significant）
- E4v2 交付检查点：no reliable difference: pass -5.1 pp [-15.4, +3.8]; efficiency changes turns, tokens_in, minutes not significant
- E4v2 grader_check：anchor tasks dropped to 0: ['pytorch-model-cli']；timeouts up +32.1 pp [+17.9, +46.2] without a pass-rate gain；cost up without a pass-rate gain: turns +171%, tokens_in +298%, minutes +66%
- E4p 契约 v1：no reliable difference: pass -2.4 pp [-8.9, +4.1]; efficiency changes turns, tokens_in, minutes not significant
- E4p 契约 v2：anchor tasks dropped to 0: ['configure-git-webserver']
- H17 条件式契约：cost up without a pass-rate gain: minutes +18%
- E4s 契约（gpt-6-sol，k=2）：baseline: 25 tasks have fewer than 3 usable attempts；candidate: infrastructure-error rate 12% > 5%；candidate: 25 tasks have fewer than 3 usable attempts
- E4s self_check（gpt-6-sol，k=2）：baseline: 25 tasks have fewer than 3 usable attempts；candidate: infrastructure-error rate 13% > 5%；candidate: 24 tasks have fewer than 3 usable attempts
- Qwen H1 接口修补：cheaper and non-inferior: turns -18%, tokens_in -41%; pass +5.0 pp, CI lower -5.0 ≥ −8.0
- Qwen H2 vs H0：no reliable difference: pass +5.8 pp [-5.0, +17.5]; efficiency changes turns, tokens_in, minutes not significant
- Qwen 交卷把关（H2 vs H1）：cost up without a pass-rate gain: turns +20%, tokens_in +67%
- 合成留出题 H2 vs H0（原版）：no reliable difference: pass -0.9 pp [-5.4, +3.6]; efficiency changes turns, tokens_in, minutes not significant
- 合成留出题 H2 vs H0（SFT）：no reliable difference: pass +2.7 pp [-3.6, +9.0]; efficiency changes turns, tokens_in, minutes not significant
- SWE-bench Verified adaptive_wait（k=1）：baseline: 20 tasks have fewer than 3 usable attempts；candidate: 20 tasks have fewer than 3 usable attempts（放宽后：no reliable difference: pass +0.0 pp [+0.0, +0.0]; efficiency changes turns, tokens_in, minutes not significant）
- 空对照 E1 → E4 基线（隔 3 小时）：pass rate +11.5 pp [+2.6, +21.8] ≥ noise floor 8.0 pp；arms were not run concurrently (D-040): downgraded to PROVISIONAL
- 空对照 E4 → E4v2 基线：no reliable difference: pass +3.8 pp [-7.7, +14.1]; efficiency changes turns, tokens_in, minutes not significant
- 空对照 E4p → H17 基线（41 题）：no reliable difference: pass +0.0 pp [-8.1, +7.3]; efficiency changes turns, tokens_in, minutes not significant
- 空对照 Qwen H0 两批（k=2）：baseline: 30 tasks have fewer than 3 usable attempts；candidate: 30 tasks have fewer than 3 usable attempts（放宽后：no reliable difference: pass -1.7 pp [-11.7, +8.3]; efficiency changes turns, tokens_in, minutes not significant）
- 空对照 Qwen 原版 合成留出题（隔一天）：cheaper and non-inferior: minutes -22%; pass +2.7 pp, CI lower -0.9 ≥ −8.0；arms were not run concurrently (D-040): downgraded to PROVISIONAL
- 空对照 Qwen 原版 TB（隔一天）：cheaper and non-inferior: minutes -20%; pass +5.8 pp, CI lower -4.2 ≥ −8.0；arms were not run concurrently (D-040): downgraded to PROVISIONAL
- 空对照 Qwen SFT 合成留出题（隔一天）：cheaper, but the pass-rate CI cannot rule out a drop larger than the noise floor (-2.7 pp [-9.0, +2.7]); needs a larger confirmation batch

## 空对照：同一配置的 trial 随机分成两半当成两个臂（每个 job 抽 200 次）

| job（@ 后是锚题用的更早批次） | 抽样次数 | 决定分布 | 误收率（ACCEPT_*） | 误拒率（REJECT） |
|---|---|---|---|---|
| qeval-base-tb+qfinal-base-tb @ qarm-h2-gate+qarm2-h2-gate | 200 | {'INCONCLUSIVE': 175, 'ACCEPT_QUALITY': 5, 'ACCEPT_EFFICIENCY': 5, 'REJECT': 13, 'PROVISIONAL': 2} | 5.0% | 6.5% |
| qeval-base-tb+qfinal-base-tb | 200 | {'INCONCLUSIVE': 171, 'ACCEPT_QUALITY': 5, 'ACCEPT_EFFICIENCY': 5, 'REJECT': 17, 'PROVISIONAL': 2} | 5.0% | 8.5% |
| qeval-base-synth+qfinal-base-synth | 200 | {'ACCEPT_QUALITY': 2, 'INCONCLUSIVE': 173, 'REJECT': 18, 'ACCEPT_EFFICIENCY': 7} | 4.5% | 9.0% |
| e4p-baseline+h17-baseline @ e1-baseline-seed | 200 | {'INCONCLUSIVE': 173, 'ACCEPT_QUALITY': 8, 'REJECT': 11, 'PROVISIONAL': 4, 'ACCEPT_EFFICIENCY': 4} | 6.0% | 5.5% |
| qarm-h0-baseline+qarm2-h0-baseline | 200 | {'REJECT': 88, 'INCONCLUSIVE': 98, 'ACCEPT_QUALITY': 7, 'ACCEPT_EFFICIENCY': 5, 'PROVISIONAL': 2} | 6.0% | 44.0% |
