# Harbor PR 草稿：Terminus 2 的 `_execute_commands` 超时分支不可达 + 可选的"命令完成哨兵"等待

（针对 harbor 0.23.0，`harbor/agents/terminus_2/terminus_2.py` 与 `tmux_session.py`；行号以该版本为准）

## 1. 问题：`except TimeoutError` 是死代码

`terminus_2.py:1338-1351`：

```python
for command in commands:
    try:
        await session.send_keys(command.keystrokes, block=False, min_timeout_sec=command.duration_sec)
    except TimeoutError:
        return True, self._timeout_template.format(...)
```

`send_keys(block=False)` 走的是 `tmux_session.py:765` 的 `_send_non_blocking_keys`，它只做 `asyncio.sleep(min_timeout_sec - elapsed)`，**从不 raise**。
只有 `_send_blocking_keys`（`tmux_session.py:747`）会在 `timeout {max}s tmux wait done` 非零退出时 raise `TimeoutError`，而 Terminus 2 从不以 `block=True` 调用。
结果：`_timeout_template` 永远不会被格式化，模型永远不会收到"命令超时"的提示；`_TMUX_COMPLETION_COMMAND = "; tmux wait -S done"`（`tmux_session.py:19`）在 Terminus 2 路径下也从不被追加。

影响：模型对每条命令只能靠自己猜 `duration_sec`，猜短了就多花一轮 `""`（空按键）去等（我们在 Terminal-Bench 2.1 × Seed lite 上测到平均每 trial 0.45 轮是纯等待，失败 trial 里 13% 被判官归为 POLLING）。

## 2. 顺带：固定通道名 `done` 有竞争风险

`_TMUX_COMPLETION_COMMAND` 用固定通道 `done`。若同一 session 里两条命令先后带哨兵发出（或上一条超时后仍在跑），`tmux wait -S done` 的信号会串到错误的等待者。建议每条命令用唯一通道名（如 `ae<n>`），我们的实现见下。

## 3. 建议改动（两种，任选）

**A. 最小改动（诚实化）**：删掉 `except TimeoutError` 分支和 `_timeout_template` 的相关引用，或在 docstring 里注明 non-blocking 路径不会超时。零行为变化。

**B. 可选的自适应等待（我们已在 fork 里实现并跑了 78 trial）**：`Terminus2Options` 加 `adaptive_wait: bool = False`。开启时，对"简单命令"（单行、非交互、非 `&` 后台）追加 `; tmux wait -S <唯一通道>`，然后 `timeout min(duration_sec, cap) tmux wait <通道>`：
- 哨兵先返回 → 立刻取输出，不再空等；
- 到 cap 未返回 → 退回上游行为（取当前屏幕，让模型决定继续等还是干预），并在观察末尾附一行提示；
- 识别到交互式提示（`^:\s*$`、`(END)`、`Password:` 等整行匹配）时不追加哨兵。

实现：`terminus2_patches/tmux_adaptive.py::AdaptiveTmuxSession.run_adaptive`（约 60 行），`terminus2_patches/agent.py::Terminus2Patched._execute_commands`。

## 4. 我们测到的数据（Terminal-Bench 2.1，26 题 × k=3，Seed lite，同批次基线对照）

| 指标 | 基线 | adaptive_wait | 变化 |
|---|---|---|---|
| 空等待轮 / trial | 0.45 | 0.33 | −27% |
| 平均轮数 | 14.4 | 13.7 | −0.6 |
| 输入 token / trial | 227.6k | 201.8k | −11% |
| trial 级通过率 | 61.5% | 59.0% | −2.6 pp [−14.1, +9.0]，在 8 pp 噪声底内 |
| 哨兵正常返回的命令占比 | — | ~70%（1494+ 条） | — |
| 识别为交互提示、未追加哨兵 | — | 65 次 | — |

结论：省轮次、省 token，通过率无可测变化；默认关闭、不改变现有行为，适合作为可选项。

## 5. 待 PR 前要做的事

- [ ] 在 Harbor main 上重跑 `tests/` 里的 golden 测试（全关 == 上游）
- [ ] 把 `AdaptiveTmuxSession` 合并进 `TmuxSession.send_keys` 的 `block=True` 路径而不是子类
- [ ] 补一个单元测试：固定通道 `done` 的串信号复现 + 唯一通道修复

## 6. 另一个问题：agent 日志目录挂进了容器，agent 能读到自己的轨迹

`/logs/agent/trajectory.json` 在容器内可读。我们观察到一条轨迹（extract-elf）执行 `find / -name '*test*' -o -name '*ref*'` 后去 grep 自己的轨迹日志找 "reference"。建议：轨迹在 host 侧写到不挂载的路径、结束时再拷入 `agent_dir`，或把挂载目录设为 agent 用户不可读。评测卫生问题，不是分数问题。
