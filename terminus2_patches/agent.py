"""Terminus 2 的可开关改动（fork 而不改上游）。

所有开关默认关闭；全关时行为与上游逐字节一致（tests/test_patched_agent.py）。
落点见 docs/DESIGN.md §6。上游钩子：
  setup()                       会话创建（adaptive_wait 用子类会话）
  _get_parser()                 interface_fixes 换宽松解析器（lenient_parser.py）
  _get_prompt_template_path()   task_contract 换模板
  _build_skills_section()       interface_fixes 开跑前环境探测，附在第一条提示的题面后
  _handle_llm_interaction()     task_contract 首轮只读校验；记下每轮 analysis / plan（completion_gate 用）与原始回复（raw_log）
  _get_completion_confirmation_message()  verifier_gate=self_check | grader_check；completion_gate 打回一次
  _execute_commands()           adaptive_wait；记下实际执行的命令；末尾注入（deliverable_checkpoint、续行提示）——D-009：只追加在最新观察末尾
  run()                         contract_conditional 开跑前的清晰度评分（H17）；把本 fork 的统计写进 context.metadata["patched"]
用法：harbor run -a terminus2_patches.agent:Terminus2Patched ... --ak verifier_gate=grader_check
Qwen 的四臂实验（docs/QWEN_PLAN.md §2）：H0 全关；H1 interface_fixes；H2 interface_fixes + completion_gate；三臂都开 raw_log。

已退役（D-039，负结果留在 decisions.md / HYPOTHESES.md）：stuck_reminder（从未触发）、budget_hint、exit_code_prompt（无效）、
assumption_ledger（无单独证据）、verifier_gate=auditor（0 提升、成本 +29%）、read_file_tool（未实现）。
"""
from __future__ import annotations

import asyncio
import json
import re
import shlex
import time
from pathlib import Path
from typing import Literal

from pydantic import Field

from harbor.agents.terminus_2.terminus_2 import Command, Terminus2, Terminus2Options
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths

from terminus2_patches.helpers import (admission_quote, ends_in_continuation_prompt, extract_deliverables, extract_json_fields,
                                       is_write_command, no_run_after_last_write)
from terminus2_patches.lenient_parser import LenientJSONParser
from terminus2_patches.teacher import MARK, SYSTEM as TEACHER_SYSTEM, Breaker, build_user, parse_hint, render_view
from terminus2_patches.tmux_adaptive import AdaptiveTmuxSession

HERE = Path(__file__).parent
# interface_fixes 的环境探测要查的命令：阶段 0 里 Qwen 撞到 “command not found” 最多的（file、ps、netstat、hexdump、git、ss、curl、
# sqlite3、xxd …）加上常用的解释器、编译器、编辑器和包管理器
PROBE_CMDS = ("python3", "python", "pip3", "pip", "gcc", "g++", "make", "cmake", "git", "curl", "wget", "file", "ps", "netstat", "ss",
              "lsof", "hexdump", "xxd", "od", "strings", "sqlite3", "jq", "bc", "vim", "vi", "nano", "node", "npm", "java", "go",
              "cargo", "Rscript", "sudo", "systemctl", "apt-get", "apk", "yum")
CONTINUATION_NOTE = ("[harness] The shell is showing the '>' continuation prompt: it is still waiting for the rest of an unfinished command "
                     "(an unclosed quote, or a heredoc without its end marker), so that command has NOT run. Send C-c to cancel it, "
                     "then send the whole command again in complete form.")
GATE_NO_RUN = ("[harness] You marked the task complete, but after your last change to the files you have not run anything that "
               "exercises the result (echo, cat and ls only display text; they are not checks). Run the program, script or tests the "
               "task describes, the way a grader would, and read the real output. If it fails or shows errors, fix the problem. "
               'Keep "task_complete" false until you have seen a real check pass.')
GATE_ADMIT = ('[harness] You marked the task complete, but your own analysis says: "{quote}". If anything is not actually done or does '
              'not work, do not finish yet: keep "task_complete" false and continue working on it. Never leave placeholder or '
              "made-up values in the deliverables.")


class Terminus2PatchedOptions(Terminus2Options):
    verifier_gate: Literal["none", "self_check", "grader_check"] = Field(
        default="none", description="完成前核查：none | self_check（同一对话自查）| grader_check（第二圈：像验收一样自测的具体清单）")
    adaptive_wait: bool = Field(default=False, description="等待策略：哨兵 + 超时 + 交互提示正则（D-021）")
    wait_stable_sec: float = Field(default=3.0, description="adaptive_wait 退化路径：屏幕连续无变化秒数")
    wait_cap_sec: float = Field(default=30.0, description="adaptive_wait 单条命令最长等待（与模型 duration 取大）")
    task_contract: bool = Field(default=False, description="开工前拆解：requirements / ambiguities 字段 + 第一轮只读")
    contract_version: int = Field(default=1, description="1 = E4 的契约；2 = infer 模式：模糊点类别清单 + 第二轮必须解决 + resolutions 字段 + 收尾逐条对账（D-042）")
    contract_conditional: bool = Field(default=False, description="H17：配合 task_contract（v1）。开跑前 harness 单独调一次模型给题面打清晰度分"
                                       "（clarity_v1 口径），任一维 ≥2 才用契约模板，否则整道题走上游模板（D-049）")
    gate_timeout_sec: float = Field(default=180.0, description="contract_conditional 评分调用的超时（离线预检 p90 79 s、最长 176 s）；超时或出错按清晰题处理")
    deliverable_checkpoint: bool = Field(default=False, description="第二圈：到时间阈值时若题面里的交付文件还不存在，提醒先写出当前最好答案")
    checkpoint_after_sec: float = Field(default=480.0, description="deliverable_checkpoint 第一次触发的墙钟秒数（TB 多数题 900 s 超时）")
    checkpoint_repeat_sec: float = Field(default=180.0, description="之后每隔多少秒再检查一次（最多 3 次）")
    interface_fixes: bool = Field(default=False, description="H1（Qwen）：接口修补，全部不占模型轮次——宽松解析（lenient_parser.py）、"
                                  "开跑前环境探测（有 / 没有哪些命令）附在题面后、终端停在续行提示 '>' 时在观察末尾说明")
    completion_gate: bool = Field(default=False, description="H2（Qwen）：交卷把关。第一次宣布完成时，若“最后一次改文件后没再运行过任何东西”"
                                  "或“analysis / plan 里承认没做成”，打回一次（每个 trial 最多一次），之后照上游确认")
    raw_log: bool = Field(default=False, description="每轮模型原始回复写进 agent/raw_responses.jsonl；不改轨迹格式"
                          "（上游 raw_content 模式会去掉 tool_calls，规则标签和判官都读 tool_calls）")
    teacher_hint: bool = Field(default=False, description="实时 Teacher 提示（D-069，照实习的 teacher-guided rollout）：每 hint_every 轮、"
                               "以及模型宣布完成时，Teacher 看题面 + 知识（参考解与隐藏测试）+ 最近的命令与输出，可插一句针对性短提示")
    teacher_model: str = Field(default="gpt-6-sol")
    teacher_api_key_env: str = Field(default="TEACHER_API_KEY", description="Teacher 的 key 所在环境变量（与 Student 的 OPENAI_API_KEY 分开）")
    teacher_knowledge: str = Field(default="", description="JSON：{题目短名: 只给 Teacher 看的知识}；开了 teacher_hint 却查不到 → 直接报错")
    hint_every: int = Field(default=6, description="每隔多少轮做一次例行检查")
    hint_max: int = Field(default=3, description="每次 rollout 最多送达几条提示")
    hint_max_words: int = Field(default=60)
    teacher_max_calls: int = Field(default=6, description="每次 rollout 最多调用 Teacher 几次（控成本）")
    teacher_timeout_sec: float = Field(default=150.0)


class Terminus2Patched(Terminus2):
    options_model = Terminus2PatchedOptions
    options: Terminus2PatchedOptions

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ledger: dict = {}
        self._contract_active = self.options.task_contract
        self._run_start = time.time(); self._checkpoint_fired = 0; self._deliverables: list[str] = []
        self._patched_stats: dict = self._fresh_stats([])
        self._executed: list[str] = []; self._last_text = ""; self._gate_rejections = 0; self._raw_log_path: Path | None = None
        self._turns: list[dict] = []; self._claim_this_turn = False; self._claim_hint: str | None = None
        self._teacher_ctx: dict | None = None; self._breaker = Breaker(3)

    @staticmethod
    def _fresh_stats(deliverables: list[str]) -> dict:
        return {"first_turn_rejections": 0, "adaptive": [], "contract_gate": None,
                "checkpoint_checks": 0, "checkpoint_missing": 0, "deliverables": list(deliverables),
                "parse_fixes": {}, "env_probe": None, "continuation_notes": 0,
                "completion_gate_checks": 0, "completion_gate": [],
                "teacher": {"calls": [], "hints": [], "breaker_open": False}}

    @staticmethod
    def name() -> str:
        return "terminus-2-patched"

    def version(self) -> str | None:
        return "2.0.0+patched.1"

    @property
    def all_flags_off(self) -> bool:
        o = self.options
        return (o.verifier_gate == "none" and not o.adaptive_wait and not o.task_contract and not o.deliverable_checkpoint
                and not o.interface_fixes and not o.completion_gate and not o.teacher_hint)

    # ---------------------------------------------------------------- setup
    async def setup(self, environment: BaseEnvironment) -> None:
        if not self.options.adaptive_wait:
            try:
                return await super().setup(environment)
            except RuntimeError as e:
                if "Failed to start tmux session" in str(e):
                    await self._dump_tmux_start_debug(environment)
                raise
        if self.options.record_terminal_session:
            local_rec = environment.trial_paths.agent_dir / "recording.cast"
            remote_rec = EnvironmentPaths.agent_dir / "recording.cast"
        else:
            local_rec = remote_rec = None
        self._session = AdaptiveTmuxSession(session_name=self.name(), environment=environment,
                            logging_path=EnvironmentPaths.agent_dir / "terminus_2.pane",
                            local_asciinema_recording_path=local_rec, remote_asciinema_recording_path=remote_rec,
                            pane_width=self.options.tmux_pane_width, pane_height=self.options.tmux_pane_height,
                            extra_env=self._extra_env, user=environment.default_user)
        await self._session.start()

    async def _dump_tmux_start_debug(self, environment: BaseEnvironment) -> None:
        """上游只打印 stderr，而 docker compose exec 把错误并进 stdout；把真实输出写进 agent 目录，便于诊断镜像不兼容。"""
        cmd = ("set -x; id; echo HOME=$HOME; command -v bash tmux; tmux -V; ls -ld /tmp /logs /logs/agent; "
               + self._session._tmux_start_session + "; echo start_rc=$?; tmux ls")
        try:
            r = await environment.exec(command=cmd, user=environment.default_user)
            text = f"rc={r.return_code}\n--- stdout\n{r.stdout}\n--- stderr\n{r.stderr}\n"
        except Exception as e:  # noqa: BLE001
            text = f"debug exec failed: {e!r}\n"
        try:
            (environment.trial_paths.agent_dir / "tmux_start_debug.txt").write_text(text)
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- parser / first prompt（H1）
    def _get_parser(self):
        if self.options.interface_fixes and self.options.parser_name == "json":
            return LenientJSONParser()
        return super()._get_parser()

    async def _build_skills_section(self, environment: BaseEnvironment) -> str | None:
        """上游在这里把 skills 列表接到题面后面；interface_fixes 顺带接上环境探测结果（不占模型轮次）。"""
        base = await super()._build_skills_section(environment)
        if not self.options.interface_fixes:
            return base
        probe = await self._probe_environment(environment)
        return ((base or "") + probe) or None

    async def _probe_environment(self, environment: BaseEnvironment) -> str:
        """开跑前在容器里查一次：系统版本、Python 版本、PROBE_CMDS 里哪些命令有 / 没有。只看机器本身，不碰 tests/ 和 solution/。"""
        cmd = ('. /etc/os-release 2>/dev/null; echo "os=${PRETTY_NAME:-unknown}"; echo "py=$(python3 --version 2>&1 | head -1)"; '
               f"for c in {' '.join(PROBE_CMDS)}; do if command -v $c >/dev/null 2>&1; then echo have=$c; else echo miss=$c; fi; done")
        try:
            r = await environment.exec(command=f"bash -lc {shlex.quote(cmd)}", user=environment.default_user, timeout_sec=30)
            out = r.stdout or ""
        except Exception as e:  # noqa: BLE001
            self._patched_stats["env_probe"] = {"error": repr(e)[:300]}
            return ""
        kv = [l.split("=", 1) for l in out.splitlines() if "=" in l]
        have = [v for k, v in kv if k == "have"]
        miss = [v for k, v in kv if k == "miss"]
        os_name = next((v for k, v in kv if k == "os"), "unknown")
        py = next((v for k, v in kv if k == "py"), "")
        if not have and not miss:
            self._patched_stats["env_probe"] = {"error": "empty probe output", "raw": out[:300]}
            return ""
        self._patched_stats["env_probe"] = {"os": os_name, "python": py, "have": have, "miss": miss}
        py_part = f"; {py}" if py.startswith("Python") else ""
        return ("\n\n[Harness note: facts about this machine, checked automatically before you started. This is not part of the task.]\n"
                f"- System: {os_name}{py_part}\n"
                f"- Installed commands: {', '.join(have) or 'none of the common ones'}\n"
                f"- NOT installed (install them first, or use an alternative): {', '.join(miss) or 'none'}")

    # ---------------------------------------------------------------- prompts
    def _get_prompt_template_path(self) -> Path:
        if self.options.task_contract and self.options.parser_name == "json":
            return HERE / "templates" / ("terminus-json-contract-v2.txt" if self.options.contract_version >= 2 else "terminus-json-contract.txt")
        return super()._get_prompt_template_path()

    def _get_completion_confirmation_message(self, terminal_output: str) -> str:
        if self._claim_hint:   # Teacher 在宣布完成这一轮认为还没做对：不进入交卷确认，发回提示让它接着做
            hint, self._claim_hint = self._claim_hint, None
            self._pending_completion = False
            return f"Current terminal state:\n{terminal_output}\n\n{MARK}{hint}"
        if self.options.completion_gate:
            self._patched_stats["completion_gate_checks"] += 1
            if self._gate_rejections < 1:
                reasons, msgs = [], []
                if no_run_after_last_write(self._executed):
                    reasons.append("no_run_after_last_write"); msgs.append(GATE_NO_RUN)
                quote = admission_quote(self._last_text)
                if quote:
                    reasons.append("admission"); msgs.append(GATE_ADMIT.format(quote=quote.replace('"', "'")))
                if reasons:
                    self._gate_rejections += 1
                    self._pending_completion = False   # 上游刚把它设成 True；打回后，下一次宣布完成重新走一遍确认
                    self._patched_stats["completion_gate"].append({"turn": self._n_episodes, "reasons": reasons, "quote": quote})
                    return f"Current terminal state:\n{terminal_output}\n\n" + "\n\n".join(msgs)
        if self.options.verifier_gate == "grader_check" and self.options.parser_name == "json":
            paths = ", ".join(self._deliverables) if self._deliverables else "the output files the task names"
            return (f"Current terminal state:\n{terminal_output}\n\n"
                    "Before this is graded, verify it THE WAY A GRADER WOULD, in this response (run the commands; do not just assert):\n"
                    "1. Run the task's commands LITERALLY as written in the instruction (same paths, same user/host/port/field names, same invocation), not your own paraphrase of them.\n"
                    "2. Verify from a FRESH, non-interactive process (e.g. `bash -c '...'`, `env -i bash -c '...'`, or a Python subprocess) so that anything you set only in this shell (PATH, exports, cwd) does not mask a failure.\n"
                    f"3. Confirm each required output exists and has the required format: {paths}.\n"
                    "4. If the instruction mentions a specific scenario (an interrupt, a second binary, a different user, an interactive program), exercise that exact scenario once.\n"
                    'If any check fails or cannot be run, fix it and set task_complete to false. Only if every check passed with visible evidence, include "task_complete": true again.')
        if self._contract_active and self.options.contract_version >= 2 and self.options.verifier_gate == "none" and self.options.parser_name == "json" and self._ledger.get("ambiguities"):
            amb = json.dumps(self._ledger.get("ambiguities"), ensure_ascii=False)[:1800]
            res = json.dumps(self._ledger.get("resolutions"), ensure_ascii=False)[:1200] if self._ledger.get("resolutions") else "none recorded"
            return (f"Current terminal state:\n{terminal_output}\n\n"
                    "Before this is graded, reconcile your contract IN THIS RESPONSE. Ambiguities you listed on turn 1:\n" + amb +
                    "\nResolutions you recorded so far:\n" + res +
                    "\nFor EACH point state: which reading your deliverable follows, and whether it would still pass under the other reading. "
                    "If any point is unresolved or your deliverable only works under one reading that the task text does not guarantee, fix that first "
                    '(prefer the stricter/more general behaviour) and set task_complete to false. Otherwise include "task_complete": true again.')
        if self.options.verifier_gate != "self_check" or self.options.parser_name != "json":
            return super()._get_completion_confirmation_message(terminal_output)
        return (f"Current terminal state:\n{terminal_output}\n\n"
                "Before this is graded, do a self-check IN THIS RESPONSE: re-read the original task, list each concrete requirement "
                "(exact paths, formats, values, restrictions), and for each one state the evidence from the terminal output above that it is "
                "satisfied. If any requirement lacks direct evidence, run the commands that would produce it (and set task_complete to false). "
                'Only if every requirement has evidence, include "task_complete": true again.')

    # ---------------------------------------------------------------- per-turn hook
    async def _handle_llm_interaction(self, chat, prompt, original_instruction="", session=None):
        commands, is_task_complete, feedback, analysis, plan, llm_response = await super()._handle_llm_interaction(
            chat, prompt, original_instruction, session)
        extra_warnings: list[str] = []
        o = self.options
        fix = getattr(self._parser, "last_fix", None)
        if fix:
            self._patched_stats["parse_fixes"][fix] = self._patched_stats["parse_fixes"].get(fix, 0) + 1
        self._last_text = f"{analysis}\n{plan}"
        self._claim_this_turn = bool(is_task_complete and not self._pending_completion and not (feedback and "ERROR:" in feedback))
        if o.raw_log and self._raw_log_path is not None:
            try:
                with open(self._raw_log_path, "a") as f:
                    f.write(json.dumps({"turn": self._n_episodes, "content": llm_response.content,
                                        "reasoning_content": llm_response.reasoning_content,
                                        "parse_error": feedback if "ERROR:" in (feedback or "") else None,
                                        "fix": fix, "task_complete": is_task_complete}, ensure_ascii=False) + "\n")
            except Exception:  # noqa: BLE001
                pass

        if self._contract_active and o.contract_version >= 2 and self._n_episodes > 1:
            res = extract_json_fields(llm_response.content or "", ("resolutions",)).get("resolutions")
            if res:
                self._ledger["resolutions"] = res
        # task_contract：首轮只读；记录 requirements / ambiguities
        if self._contract_active and self._n_episodes == 1 and not (feedback and "ERROR:" in feedback):
            fields = extract_json_fields(llm_response.content or "", ("requirements", "ambiguities"))
            if fields:
                self._ledger.update(fields)
            offenders = [c.keystrokes for c in commands if is_write_command(c.keystrokes)]
            if offenders:
                self._patched_stats["first_turn_rejections"] += 1
                if self._patched_stats["first_turn_rejections"] <= 2:
                    return ([], False, "ERROR: your FIRST response must contain only read-only commands (look before you act). "
                            f"Rejected: {offenders[:3]!r}. Resend the same JSON (keep requirements/ambiguities) with read-only commands only.",
                            analysis, plan, llm_response)

        if extra_warnings:
            joined = "\n\n".join(extra_warnings)
            feedback = (feedback + "\n" if feedback else "") + ("" if feedback and "WARNINGS:" in feedback else "WARNINGS: ") + joined
        return commands, is_task_complete, feedback, analysis, plan, llm_response

    # ---------------------------------------------------------------- execution + tail injection
    async def _execute_commands(self, commands: list[Command], session):
        o = self.options
        self._executed.extend(c.keystrokes for c in commands)   # completion_gate 按实际执行的命令判断
        if o.adaptive_wait and isinstance(session, AdaptiveTmuxSession):
            notes = []
            for c in commands:
                if not c.keystrokes.strip():  # 空等待照上游
                    await session.send_keys(c.keystrokes, block=False, min_timeout_sec=c.duration_sec)
                    continue
                info = await session.run_adaptive(c.keystrokes, c.duration_sec, o.wait_cap_sec, o.wait_stable_sec)
                self._patched_stats["adaptive"].append(info)
                if info["finished"] is False:
                    notes.append(f"[harness] the command is still running after {info['waited_sec']}s (no shell prompt yet). "
                                 "Send empty keystrokes to keep waiting, or C-c to interrupt.")
                if info["prompt"]:
                    notes.append(f"[harness] the terminal appears to be waiting for input: {info['prompt']!r}. Answer it or send C-c.")
            terminal_output = self._limit_output_length(await session.get_incremental_output())
            if notes:
                terminal_output += "\n" + "\n".join(dict.fromkeys(notes))
            timeout_occurred = False
        else:
            timeout_occurred, terminal_output = await super()._execute_commands(commands, session)
        # D-009：动态内容只追加在末尾
        tail = []
        if o.deliverable_checkpoint and self._deliverables and self._checkpoint_fired < 3:
            elapsed = time.time() - self._run_start
            due = o.checkpoint_after_sec + self._checkpoint_fired * o.checkpoint_repeat_sec
            if elapsed >= due:
                missing = await self._missing_deliverables(session)
                self._checkpoint_fired += 1
                self._patched_stats["checkpoint_checks"] += 1
                if missing:
                    self._patched_stats["checkpoint_missing"] += 1
                    tail.append(f"[harness checkpoint] {int(elapsed // 60)} min elapsed; required output {', '.join(missing)} does not exist yet. "
                                "Write your current best answer to it NOW (even if imperfect), then keep refining. A missing file scores zero.")
        if o.interface_fixes and ends_in_continuation_prompt(terminal_output):
            self._patched_stats["continuation_notes"] += 1
            tail.append(CONTINUATION_NOTE)
        self._turns.append({"turn": self._n_episodes, "commands": [c.keystrokes for c in commands], "output": terminal_output})
        if o.teacher_hint:
            if self._claim_this_turn:
                hint = await self._teacher_hint("The agent just declared the task complete. Interrupt only if its work would still fail "
                                                "or is unverified.")
                if hint:   # 交给 _get_completion_confirmation_message 发出
                    self._claim_hint = hint
                    self._patched_stats["teacher"]["hints"].append({"turn": self._n_episodes, "text": hint, "at_claim": True,
                                                                    "claim_had_commands": any(c.keystrokes.strip() for c in commands)})
            elif self._n_episodes % max(1, o.hint_every) == 0:
                hint = await self._teacher_hint(f"Routine check after turn {self._n_episodes}.")
                if hint:
                    tail.append(MARK + hint)
                    self._patched_stats["teacher"]["hints"].append({"turn": self._n_episodes, "text": hint, "at_claim": False})
        if tail:
            terminal_output = terminal_output + "\n\n" + "\n".join(tail)
        return timeout_occurred, terminal_output

    async def _clarity_gate(self, instruction: str) -> dict:
        """H17：开跑前单独调一次被测模型，按 clarity_v1 给题面打 0–3 分（只看题面，不看容器和测试）。
        任一维 ≥2 → on（用契约模板）；超时或出错 → off（走上游）。走上游同一个 LLM 封装（同 key、同重试、同计费），
        这次调用算在 agent 的时限和成本里。"""
        gate = {"on": False, "intent": None, "target": None, "latency_sec": None, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "error": None}
        t0 = time.time()
        try:
            r = await asyncio.wait_for(self._llm.call(
                prompt=f"INSTRUCTION:\n{instruction.strip()}",
                message_history=[{"role": "system", "content": (HERE / "prompts" / "clarity_gate.txt").read_text()}]),
                timeout=self.options.gate_timeout_sec)
            raw = r.content or ""
            if r.usage is not None:
                gate["tokens_in"], gate["tokens_out"] = r.usage.prompt_tokens, r.usage.completion_tokens
                gate["cost_usd"] = float(r.usage.cost_usd or 0.0)
            gate["intent"], gate["target"] = _clarity_score(raw, "intent_clarity"), _clarity_score(raw, "target_certainty")
            gate["on"] = (gate["intent"] or 0) >= 2 or (gate["target"] or 0) >= 2
            gate["raw"] = raw[:1500]
        except Exception as e:  # noqa: BLE001
            gate["error"] = repr(e)[:300]
        gate["latency_sec"] = round(time.time() - t0, 1)
        return gate

    async def _teacher_call(self, system: str, user: str) -> tuple[str, dict]:
        """一次 Teacher 调用（阻塞的 HTTP 请求放到线程里，不卡住同一进程里其他 trial）。返回 (文本, usage)。"""
        from agenteval.judge.client import JudgeClient
        cli = JudgeClient(self.options.teacher_model, api_key_env=self.options.teacher_api_key_env, reasoning_effort="low", max_tokens=3000)
        text = await asyncio.wait_for(asyncio.to_thread(cli.complete, system, user, False), timeout=self.options.teacher_timeout_sec)
        return text, dict(cli.usage)

    async def _teacher_hint(self, moment: str) -> str | None:
        """按上限与熔断决定是否调用 Teacher；返回要送达的提示或 None。每次调用都记账（送没送、为什么没送）。"""
        o, st = self.options, self._patched_stats["teacher"]
        delivered = len(st["hints"])
        reason = ("breaker_open" if self._breaker.open else "call_cap" if len(st["calls"]) >= o.teacher_max_calls
                  else "hint_cap" if delivered >= o.hint_max else None)
        if reason:
            return None
        ctx = self._teacher_ctx or {}
        user = build_user(ctx.get("instruction", ""), ctx.get("knowledge", ""), render_view(self._turns), moment)
        t0 = time.time(); rec = {"turn": self._n_episodes, "moment": moment[:40]}
        try:
            text, usage = await self._teacher_call(TEACHER_SYSTEM.format(max_words=o.hint_max_words), user)
            self._breaker.record(True)
            d = parse_hint(text, o.hint_max_words)
            rec.update(delivered=d.deliver, drop_reason=d.drop_reason, usage=usage)
        except Exception as e:  # noqa: BLE001  Teacher 故障不拖累 Student
            self._breaker.record(False)
            d = None
            rec.update(delivered=False, drop_reason=f"teacher_error: {e!r}"[:200])
        rec["latency_sec"] = round(time.time() - t0, 1)
        st["calls"].append(rec); st["breaker_open"] = self._breaker.open
        return d.text if d and d.deliver else None

    async def _missing_deliverables(self, session) -> list[str]:
        env = getattr(session, "environment", None)
        if env is None:
            return []
        missing = []
        for p in self._deliverables:
            try:
                r = await env.exec(f"test -s {shlex.quote(p)} && echo YES || echo NO")
                if "YES" not in (r.stdout or ""):
                    missing.append(p)
            except Exception:
                pass
        return missing

    # ---------------------------------------------------------------- run
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        self._ledger = {}
        self._run_start = time.time(); self._checkpoint_fired = 0
        self._deliverables = extract_deliverables(instruction) if (self.options.deliverable_checkpoint or self.options.verifier_gate == "grader_check") else []
        self._patched_stats = self._fresh_stats(self._deliverables)
        self._executed, self._last_text, self._gate_rejections = [], "", 0
        self._turns, self._claim_this_turn, self._claim_hint, self._breaker = [], False, None, Breaker(3)
        self._teacher_ctx = None
        if self.options.teacher_hint:   # 开了却缺配置 → 直接报错，绝不悄悄退化成普通 rollout（实习版的规矩）
            import os
            if not os.environ.get(self.options.teacher_api_key_env):
                raise RuntimeError(f"teacher_hint on but {self.options.teacher_api_key_env} is not set")
            name = getattr(environment, "environment_name", None) or ""
            know = json.load(open(self.options.teacher_knowledge)) if self.options.teacher_knowledge else {}
            key = name if name in know else name.split("/")[-1]
            if key not in know:
                raise RuntimeError(f"teacher_hint on but no knowledge for task {name!r}")
            self._teacher_ctx = {"instruction": instruction, "knowledge": know[key]}
        self._raw_log_path = None
        if self.options.raw_log and environment is not None:
            try:
                self._raw_log_path = environment.trial_paths.agent_dir / "raw_responses.jsonl"
            except Exception:  # noqa: BLE001
                self._raw_log_path = None
        contract_template = self._prompt_template
        self._contract_active = self.options.task_contract
        try:
            if self.options.task_contract and self.options.contract_conditional:
                gate = await self._clarity_gate(instruction)
                self._patched_stats["contract_gate"] = gate
                if not gate["on"]:  # 清晰题：本次 run 整个退回上游（模板、首轮只读、账本都不启用）
                    self._contract_active = False
                    self._prompt_template = super()._get_prompt_template_path().read_text()
            await super().run(instruction, environment, context)
        finally:
            gate = self._patched_stats.get("contract_gate")
            if gate:  # 评分调用计入本 trial 的 token 与成本
                context.n_input_tokens = (context.n_input_tokens or 0) + gate["tokens_in"]
                context.n_output_tokens = (context.n_output_tokens or 0) + gate["tokens_out"]
                if gate["cost_usd"]:
                    context.cost_usd = (context.cost_usd or 0.0) + gate["cost_usd"]
            flags = {k: getattr(self.options, k) for k in ("verifier_gate", "adaptive_wait", "task_contract", "contract_version", "contract_conditional",
                                                           "deliverable_checkpoint", "interface_fixes", "completion_gate", "raw_log",
                                                           "teacher_hint")}
            stats = dict(self._patched_stats)
            ad = stats.pop("adaptive")
            stats["adaptive_n"] = len(ad)
            stats["adaptive_sentinel_finished"] = sum(1 for a in ad if a.get("finished") is True)
            stats["adaptive_sentinel_timeout"] = sum(1 for a in ad if a.get("finished") is False)
            stats["adaptive_prompt_detected"] = sum(1 for a in ad if a.get("prompt"))
            stats["adaptive_waited_sec_total"] = round(sum(a.get("waited_sec", 0) for a in ad), 1)
            if context.metadata is None:
                context.metadata = {}
            context.metadata["patched"] = {"flags": flags, "ledger": self._ledger, **stats}
            self._prompt_template = contract_template


def _clarity_score(raw: str, key: str) -> int | None:
    m = re.search(rf"^\s*{key}:\s*\D*([0-3])", raw, re.M)
    return int(m.group(1)) if m else None
