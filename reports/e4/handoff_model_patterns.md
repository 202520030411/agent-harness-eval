# 交接包：改 harness 之后仍归责到模型的失败模式

粒度是模式级（跨配置发生率），不是单条 trial 的因果。每个模式给 3–5 条轨迹、试过的 harness 缓解、建议题型。

## PREMATURE_COMPLETION（归责：MIXED）

发生率（占全部可评 trial）：弱模型基线 26% → 改 harness 后 17%；强模型基线 12%。

**代表轨迹**（`harbor view` 可回放）：

- `cancel-async-tasks__cYtchRP`（cancel-async-tasks，4 轮，起始轮 4）：“Analysis: Both tests passed: (1) Normal run — all 5 tasks completed and peak concurrency was exactly 2, confirming the max_concurrent bound works. (2) KeyboardInterrupt test — running tasks were cancelled, their finally/”
- `configure-git-webserver__qWJPWrt`（configure-git-webserver，9 轮，起始轮 7）：“Analysis: The environment is now fully set up and clean: empty bare repository at /git/server with an executable post-receive hook that checks out any pushed branch into /git/www; python3 http.server running on port 8080”
- `dna-insert__FfgDSgg`（dna-insert，9 轮，起始轮 9）：“Analysis: All verifications passed successfully: - Forward primer annealing: 18 nt (within 15-45 range), Tm=63.81°C (within 58-72°C) - Reverse primer annealing: 45 nt (within 15-45 range), Tm=63.81°C (within 58-72°C) - T”
- `dna-insert__HmQsUT5`（dna-insert，11 轮，起始轮 11）：“Analysis: All verification checks pass: - Forward primer: 58 nt total = 39 nt insertion + 19 nt annealing region matching input at position 215 - Reverse primer: 42 nt annealing to upstream region immediately before inse”

**我们在 harness 侧试过的缓解：**

- verifier_gate=self_check：失败里 PREMATURE_COMPLETION 未明显减少；pass +6.4 pp（<δ），成本 +35%
- verifier_gate=auditor：22 次打回本身都对、但模型补不完，7 条推到超时；pass +0.0
- task_contract：PREMATURE 26%→17%/trial，主要是 SPEC 类失败减少带来的

**建议模型侧补的题型：** 带隐藏验收标准、且跑一下测试就能自检的题（让先验证再声称完成有可学的回报）

## TRUNCATED_READ（归责：MODEL）

发生率（占全部可评 trial）：弱模型基线 13% → 改 harness 后 9%；强模型基线 0%。

**代表轨迹**（`harbor view` 可回放）：

- `chess-best-move__qbkzzn3`（chess-best-move，25 轮，起始轮 7）：“Analysis: I can see the board clearly now. Background: light squares have mean ~213, dark squares ~139. Pieces: white pieces have light body + black outline; black pieces have dark body. I've classified occupied squares ”
- `configure-git-webserver__qWJPWrt`（configure-git-webserver，9 轮，起始轮 4）：“Analysis: Git is now installed successfully. Next I need to create the bare repository at /git/server, a post-receive hook that checks out pushed content into a web root (/git/www), and start a web server on port 8080 se”
- `extract-elf__KLVixQE`（extract-elf，15 轮，起始轮 3）：“Analysis: The binary is a 64-bit ELF executable, likely small, with several loaded segments. It has initialized sections (.rodata, .data, etc.) and a small .bss. We need determine exactly what 'memory values' means: prob”
- `gcode-to-text__XgoAhPp`（gcode-to-text，41 轮，起始轮 11）：“Analysis: The ASCII render shows shapes but they appear rotated. The text likely reads vertically (along Y axis). Let me transpose the view to read it horizontally. Plan: Re-render with X and Y swapped so the text orient”

**我们在 harness 侧试过的缓解：**

- adaptive_wait：失败里 TRUNCATED_READ 33%→14%（省了轮次但没省错误）
- read_file_tool：未实现（基线 TRUNCATED_READ 在失败里 33%，按 H8 门槛本应做；留作下一步）

**建议模型侧补的题型：** 输出超过一屏的文件/日志检索题，正确答案在被截断的部分之后

## BUDGET_EXHAUSTED（归责：MODEL）

发生率（占全部可评 trial）：弱模型基线 13% → 改 harness 后 14%；强模型基线 0%。

**代表轨迹**（`harbor view` 可回放）：

- `adaptive-rejection-sampler__2HFUe8G`（adaptive-rejection-sampler，5 轮，起始轮 5）：“Analysis: First three chunks of /app/ars.R are written successfully (log-density, derivatives, mode finding, hull construction/insertion, upper/lower hull evaluation). Now I need to append the proposal sampler, the publi”
- `adaptive-rejection-sampler__VFbZoXU`（adaptive-rejection-sampler，15 轮，起始轮 15）：“Analysis: The module test MOD_UPPER_HULL_ENVELOPES crashed: `k` ended up length zero, so `cc + m*xx` had length zero. Likely findInterval indexing into pp$L/pp$kn misbehaves for the envelope check (e.g., when xs equals a”
- `chess-best-move__qbkzzn3`（chess-best-move，25 轮，起始轮 25）：“Analysis: Killed the deep analysis. Let me use a time-based limit of 5 seconds with 3 PVs to get a quick but reliable answer. Plan: Run stockfish with 5 second time limit and multipv 5.”
- `gcode-to-text__XgoAhPp`（gcode-to-text，41 轮，起始轮 41）：“Analysis: The projection still shows diagonal bands - the text wall is not aligned with my assumed direction. Let me look at the per-layer X/Y centers to find the actual wall direction. Plan: Print Xcenter and Ycenter fo”

**我们在 harness 侧试过的缓解：**

- budget_hint（hygiene 臂）：无效（−1.3 pp）；轮数没有变化
- adaptive_wait：空等待轮 −27%、token −11%，但通过率不涨：省下的轮没有转成进展

**建议模型侧补的题型：** 需要 20+ 轮、中途有可复用中间产物的长任务；奖励里加轮次/token 惩罚
