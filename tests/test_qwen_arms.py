"""Qwen 四臂实验（docs/QWEN_PLAN.md §2）的 harness 改动：H1 interface_fixes、H2 completion_gate、raw_log。
解析器与 agent 的测试需要 harbor（服务器 .venv）；本地没有就跳过。"""
import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from terminus2_patches.helpers import (admission_quote, command_heads, ends_in_continuation_prompt, is_run_command,
                                       no_run_after_last_write, strip_heredoc_bodies)


# ---------------------------------------------------------------- 命令分类（H2 与离线统计共用）
def test_command_heads_skip_prefixes_and_heredoc_bodies():
    assert command_heads("cd /app && FOO=1 sudo timeout 30 python3 run.py | tee log\n") == ["cd", "python3", "tee"]
    ks = "cat > t.py << 'EOF'\nimport os\nprint(1)\nEOF\npython3 t.py\n"
    assert strip_heredoc_bodies(ks).split("\n")[:2] == ["cat > t.py ", "python3 t.py"]
    assert command_heads(ks) == ["cat", "python3"]
    assert command_heads("grep -c x <<< \"$VAR\"\npython3 a.py\n") == ["grep", "python3"]    # here-string 不吞后面的行


@pytest.mark.parametrize("ks,run", [
    ("python3 solve.py\n", True), ("pytest -q\n", True), ("./a.out < in.txt\n", True), ("make\n", True),
    ("diff out.txt expected.txt\n", True), ("curl -s localhost:8080/health\n", True), ("Rscript -e 'source(\"ars.R\")'\n", True),
    ("echo '✓ All requirements met'\n", False), ("cat /app/out.txt\n", False), ("ls -la\n", False),
    ("sed -i 's/a/b/' f.py\n", False), ("pip install numpy\n", False), ("git log --oneline\n", False),
    ("cat > f.py << 'EOF'\nimport sys\nsys.exit(0)\nEOF\n", False), ("C-c", False), ("", False),
    ("cat > f.py << 'EOF'\nx=1\nEOF\npython3 f.py\n", True),
])
def test_is_run_command(ks, run):
    assert is_run_command(ks) is run


def test_no_run_after_last_write():
    assert no_run_after_last_write(["python3 a.py\n", "cat > out.txt << 'EOF'\n42\nEOF\n", "echo '✓ done'\n"])
    assert not no_run_after_last_write(["cat > a.py << 'EOF'\nprint(1)\nEOF\n", "python3 a.py\n", "echo '✓ done'\n"])
    assert not no_run_after_last_write(["python3 gen.py > out.txt\n"])          # 既写又跑：算写完后跑过
    assert not no_run_after_last_write(["ls\n", "cat README\n"])               # 没改过文件：不触发
    assert no_run_after_last_write(["python3 a.py\n", "sed -i 's/1/2/' a.py\n"])


def test_admission_quote():
    q = admission_quote("Everything is set up. Although I couldn't get the tests to pass, the file exists.\nPlan: done")
    assert q == "Although I couldn't get the tests to pass, the file exists."
    assert admission_quote("All tests passed and the output matches the spec.") is None
    assert "placeholder" in admission_quote("I wrote a placeholder value for the key")


def test_continuation_prompt():
    assert ends_in_continuation_prompt("New Terminal Output:\nroot@x:/app# cat << EOF\n> \n")
    assert ends_in_continuation_prompt("> echo 'hi\n>")
    assert not ends_in_continuation_prompt("root@x:/app# ls\nout.txt\nroot@x:/app# ")
    assert not ends_in_continuation_prompt(">>> ")


# ---------------------------------------------------------------- 宽松解析（H1）
harbor = pytest.importorskip("harbor")
from harbor.agents.terminus_2.terminus_2 import Terminus2  # noqa: E402
from harbor.agents.terminus_2.terminus_json_plain_parser import TerminusJSONPlainParser  # noqa: E402

from terminus2_patches.agent import GATE_NO_RUN, Terminus2Patched  # noqa: E402
from terminus2_patches.lenient_parser import LenientJSONParser  # noqa: E402

VALID = '{"analysis": "look", "plan": "list", "commands": [{"keystrokes": "ls -la\\n", "duration": 0.1}], "task_complete": false}'


@pytest.mark.parametrize("resp", [VALID, VALID + "\nextra", "no json here", '{"analysis": "a"}', ""])
def test_lenient_identical_to_upstream_when_upstream_succeeds_or_fix_does_not_apply(resp):
    up, le = TerminusJSONPlainParser().parse_response(resp), LenientJSONParser().parse_response(resp)
    assert le == up


def test_lenient_control_characters_in_strings():
    resp = '{"analysis": "line1\nline2", "plan": "p", "commands": [{"keystrokes": "cat > f << \'EOF\'\nx=1\nEOF\n", "duration": 0.5}]}'
    assert "Invalid control character" in TerminusJSONPlainParser().parse_response(resp).error
    p = LenientJSONParser(); r = p.parse_response(resp)
    assert r.error == "" and r.commands[0].keystrokes == "cat > f << 'EOF'\nx=1\nEOF\n" and p.last_fix == "ctrl"


def test_lenient_task_complete_shorthand_and_missing_text():
    p = LenientJSONParser()
    r = p.parse_response('{\n    "task_complete": true\n}')
    assert r.error == "" and r.is_task_complete and r.commands == [] and p.last_fix == "task_complete_only"
    r = p.parse_response('{"analysis": "waiting", "commands": [{"keystrokes": "", "duration": 5.0}]}')
    assert r.error == "" and not r.is_task_complete and r.plan == "" and p.last_fix == "missing_text"
    r = p.parse_response('{"task_complete": false}')                 # 没有 commands 也没宣布完成：不归 H1 管
    assert "Missing required fields" in r.error and p.last_fix is None


def test_lenient_bad_escape():
    resp = '{"analysis": "a", "plan": "b", "commands": [{"keystrokes": "echo \\$HOME \\. done\\n", "duration": 0.1}]}'
    assert TerminusJSONPlainParser().parse_response(resp).error
    p = LenientJSONParser(); r = p.parse_response(resp)
    assert r.error == "" and r.commands[0].keystrokes == "echo \\$HOME \\. done\n" and p.last_fix == "escape"


# ---------------------------------------------------------------- agent 接线
def _mk(cls, **kw):
    return cls(logs_dir=Path(tempfile.mkdtemp()), model_name="openai/dummy", api_base="http://localhost:1",
               model_info={"max_input_tokens": 1000, "max_output_tokens": 100}, suppress_max_turns_warning=True, **kw)


def test_flags_and_parser_switch():
    h0, h1, h2 = _mk(Terminus2Patched, raw_log=True), _mk(Terminus2Patched, interface_fixes=True), \
        _mk(Terminus2Patched, interface_fixes=True, completion_gate=True)
    assert h0.all_flags_off and type(h0._parser) is TerminusJSONPlainParser        # raw_log 不改行为
    assert not h1.all_flags_off and isinstance(h1._parser, LenientJSONParser)
    assert h2.options.completion_gate and h1._prompt_template == _mk(Terminus2)._prompt_template


def test_completion_gate_rejects_once_then_upstream_confirmation():
    up = _mk(Terminus2)._get_completion_confirmation_message("SCREEN")
    a = _mk(Terminus2Patched, interface_fixes=True, completion_gate=True)
    a._executed = ["python3 a.py\n", "cat > out.txt << 'EOF'\n42\nEOF\n", "echo '✓ Task complete'\n"]
    a._last_text = "The answer is written. Although the script failed earlier, the output file exists."
    a._pending_completion = True                                       # 上游在调用本方法前刚设为 True
    m1 = a._get_completion_confirmation_message("SCREEN")
    assert GATE_NO_RUN in m1 and "Although the script failed earlier" in m1 and a._pending_completion is False
    assert a._patched_stats["completion_gate"][0]["reasons"] == ["no_run_after_last_write", "admission"]
    a._pending_completion = True
    assert a._get_completion_confirmation_message("SCREEN") == up      # 每个 trial 最多打回一次
    assert a._patched_stats["completion_gate_checks"] == 2


def test_completion_gate_passes_when_evidence_present():
    a = _mk(Terminus2Patched, completion_gate=True)
    a._executed = ["cat > a.py << 'EOF'\nprint(1)\nEOF\n", "python3 a.py\n", "echo '✓ done'\n"]
    a._last_text = "Ran the script; output matches."
    assert a._get_completion_confirmation_message("S") == _mk(Terminus2)._get_completion_confirmation_message("S")
    assert a._patched_stats["completion_gate"] == []


def test_env_probe_and_continuation_note():
    a = _mk(Terminus2Patched, interface_fixes=True)
    out = "os=Ubuntu 24.04.2 LTS\npy=Python 3.12.3\nhave=python3\nhave=gcc\nmiss=python\nmiss=file\n"
    async def fake_exec(command, cwd=None, env=None, timeout_sec=None, user=None):
        assert "command -v" in command and "/tests" not in command and "solution" not in command
        return SimpleNamespace(stdout=out, stderr="", return_code=0)
    env = SimpleNamespace(exec=fake_exec, default_user=None, is_dir=None)
    a.skills_dir = None
    text = asyncio.run(a._build_skills_section(env))
    assert "Ubuntu 24.04.2 LTS; Python 3.12.3" in text and "Installed commands: python3, gcc" in text and "NOT installed" in text
    assert a._patched_stats["env_probe"]["miss"] == ["python", "file"]
    h0 = _mk(Terminus2Patched)
    h0.skills_dir = None
    assert asyncio.run(h0._build_skills_section(env)) is None          # 全关：与上游一样没有附加内容


def test_raw_log_written(tmp_path):
    a = _mk(Terminus2Patched, raw_log=True, interface_fixes=True)
    a._raw_log_path = tmp_path / "raw_responses.jsonl"
    resp = SimpleNamespace(content='{"task_complete": true}', reasoning_content=None, model_name=None)
    async def fake_query(chat, prompt, original_instruction="", session=None):
        return resp
    a._query_llm = fake_query
    a._n_episodes = 3
    cmds, done, fb, *_ = asyncio.run(a._handle_llm_interaction(None, "p"))
    row = json.loads(a._raw_log_path.read_text().splitlines()[0])
    assert done and row["turn"] == 3 and row["fix"] == "task_complete_only" and row["content"] == '{"task_complete": true}'
    assert a._patched_stats["parse_fixes"] == {"task_complete_only": 1}


def test_continuation_note_appended_only_with_interface_fixes():
    class FakeSession:
        async def get_incremental_output(self):
            return "New Terminal Output:\nroot@x:/app# python3 -c 'print(1)\n> "
    for flag, expect in ((True, True), (False, False)):
        a = _mk(Terminus2Patched, interface_fixes=flag)
        timeout, out = asyncio.run(a._execute_commands([], FakeSession()))
        assert ("continuation prompt" in out) is expect and a._patched_stats["continuation_notes"] == int(expect)
