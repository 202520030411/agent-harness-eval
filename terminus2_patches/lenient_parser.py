"""H1 接口修补之一：Terminus 2 JSON 回复的宽松解析。只在上游解析失败时介入；上游能解析的回复一律用上游结果（逐字相同）。

阶段 0（Qwen3-Coder-30B-A3B，TB 2.1 干净 30 题 × 3，含 smoke）的 487 个格式错误轮里，离线重放能救回 440 个：
  ctrl                字符串里直接换行 / 制表符（JSON 标准不允许）→ json.loads(strict=False)        319 轮
  task_complete_only  只回 {"task_complete": true}（交卷确认的简写）→ 其余字段按空处理               91 轮
  missing_text        有 commands，但缺 analysis / plan → 缺的按空串                                   20 轮
  escape              非法转义（\\$ \\. 等）→ 把这个反斜杠本身转义                                        6 轮
救不回的：空回复（35，来自 Novita 那次坏掉的服务商）、字符串里的引号没转义（4）等。
修好的回复不加“请改正格式”的警告：H1 的意思是 harness 适应模型的输出习惯，不让模型为接口多花轮次。
"""
from __future__ import annotations

import json
import re

from harbor.agents.terminus_2.terminus_json_plain_parser import ParseResult, TerminusJSONPlainParser

_BAD_ESCAPE_RE = re.compile(r'\\(?![\\"/bfnrtu])')


class LenientJSONParser(TerminusJSONPlainParser):
    def __init__(self):
        super().__init__()
        self.last_fix: str | None = None   # 最近一次 parse_response 用了哪种修补（None = 上游直接解析成功或救不回）

    def parse_response(self, response: str) -> ParseResult:
        self.last_fix = None
        result = super().parse_response(response)
        if not result.error:
            return result
        fixed = self._lenient(response)
        return result if fixed is None else fixed

    def _lenient(self, response: str) -> ParseResult | None:
        js, warnings = self._extract_json_content(response)
        if not js:
            return None
        fixes = []
        try:
            data = json.loads(js)
        except json.JSONDecodeError:
            try:
                data = json.loads(js, strict=False)
                fixes.append("ctrl")
            except json.JSONDecodeError:
                try:
                    data = json.loads(_BAD_ESCAPE_RE.sub(r"\\\\", js), strict=False)
                    fixes.append("escape")
                except json.JSONDecodeError:
                    return None
        if not isinstance(data, dict):
            return None

        complete = data.get("task_complete", False)
        if isinstance(complete, str):
            complete = complete.lower() in ("true", "1", "yes")
        complete = complete is True
        if any(f not in data for f in self.required_fields):
            if complete:
                fixes.append("task_complete_only")
            elif "commands" in data:
                fixes.append("missing_text")
            else:
                return None
        if not fixes:   # 上游报的是别的错（比如命令对象缺 keystrokes）：不归 H1 管，保留上游的报错
            return None

        analysis = data.get("analysis", "")
        plan = data.get("plan", "")
        analysis = analysis if isinstance(analysis, str) else ""
        plan = plan if isinstance(plan, str) else ""
        commands_data = data.get("commands", [])
        if not isinstance(commands_data, list):
            if not complete:
                return None
            commands_data = []
        commands, err = self._parse_commands(commands_data, warnings)
        if err:
            if not complete:
                return None
            warnings.append(err)          # 与上游一致：宣布完成时命令格式错只当警告
            commands = []
        self.last_fix = "+".join(fixes) if fixes else None
        return ParseResult(commands, complete, "", "- " + "\n- ".join(warnings) if warnings else "", analysis, plan)
