"""adaptive_wait（D-021）：哨兵 + 超时 + 交互提示正则，退化到"屏幕稳定"轮询。

上游 TmuxSession 已有阻塞路径，但 (a) `_execute_commands` 不用它，(b) 哨兵通道固定为 'done'，
超时后残留的信号会让下一次等待立刻返回。这里用每次不同的通道名解决 (b)。
"""
from __future__ import annotations

import asyncio
import itertools
import shlex
import time

from harbor.agents.terminus_2.tmux_session import TmuxSession

from terminus2_patches.helpers import detect_interactive_prompt, is_simple_command


class AdaptiveTmuxSession(TmuxSession):
    _counter = itertools.count(1)

    async def run_adaptive(self, keystrokes: str, duration_sec: float, cap_sec: float, stable_sec: float) -> dict:
        """执行一条 keystrokes，返回 {mode, waited_sec, finished: bool|None, prompt: str|None}。"""
        t0 = time.time()
        if is_simple_command(keystrokes):
            ch = f"ae{next(self._counter)}"
            body = keystrokes.rstrip("\n") + f"; tmux wait -S {ch}"
            await self._send_keys_to_session([body, "Enter"], action="adaptive-blocking")
            timeout = max(duration_sec, cap_sec)
            result = await self.environment.exec(f"timeout {timeout}s tmux wait {shlex.quote(ch)}", user=self._user)
            finished = result.return_code == 0
            mode = "sentinel"
        else:
            # 多行 / heredoc / 交互程序：照上游发，再等屏幕稳定
            await self._send_non_blocking_keys([keystrokes], min_timeout_sec=duration_sec)
            finished = None
            mode = "stable-poll"
            last = await self.capture_pane(capture_entire=False)
            stable_since = time.time()
            while time.time() - t0 < max(duration_sec, cap_sec):
                await asyncio.sleep(0.5)
                cur = await self.capture_pane(capture_entire=False)
                if cur != last:
                    last, stable_since = cur, time.time()
                elif time.time() - stable_since >= stable_sec:
                    break
        screen = await self.capture_pane(capture_entire=False)
        prompt = detect_interactive_prompt(screen)
        return {"mode": mode, "waited_sec": round(time.time() - t0, 2), "finished": finished, "prompt": prompt}
