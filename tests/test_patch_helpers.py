from terminus2_patches.helpers import (StuckTracker, audit_accepts, detect_interactive_prompt, extract_json_fields,
                                       is_simple_command, is_write_command, parse_audit)


def test_simple_command_classification():
    assert is_simple_command("ls -la\n")
    assert is_simple_command("python3 solve.py && cat out.txt\n")
    assert not is_simple_command("")                       # 空等待
    assert not is_simple_command("cat > f.txt <<'EOF'\nhi\nEOF\n")
    assert not is_simple_command("sleep 100 &\n")
    assert not is_simple_command("vim file.txt\n")
    assert not is_simple_command("python3\n")
    assert not is_simple_command("ls")                     # 没回车不执行


def test_write_command_detection():
    assert is_write_command("echo hi > out.txt\n")
    assert is_write_command("sed -i 's/a/b/' f\n")
    assert is_write_command("pip install numpy\n")
    assert is_write_command("cat > x.py <<'EOF'\n")
    assert not is_write_command("cat README.md\n")
    assert not is_write_command("grep -rn main src/\n")
    assert not is_write_command("git status\n")


def test_prompt_detection_and_stuck():
    assert detect_interactive_prompt("Do you want to continue? [Y/n] ") is not None
    assert detect_interactive_prompt("root@box:/app# ") is None
    assert detect_interactive_prompt("Disassembly of section .text:") is None   # 行尾冒号不是提示符
    assert detect_interactive_prompt("some output\n:") is not None            # less 的提示符是整行一个冒号
    st = StuckTracker()
    assert [st.observe(["make\n"]) for _ in range(3)] == [1, 2, 3]
    assert st.observe(["ls\n"]) == 1


def test_json_fields_and_audit_parse():
    c = 'prefix {"analysis":"a","plan":"p","requirements":["r1"],"ambiguities":[{"point":"x"}],"commands":[]} suffix'
    f = extract_json_fields(c, ("requirements", "ambiguities"))
    assert f["requirements"] == ["r1"] and f["ambiguities"][0]["point"] == "x"
    v = parse_audit("Status: complete\nIntegrity: clean\nContract audit: aligned\n\nConstraint backcheck:\n- ok")
    assert v and audit_accepts(v)
    v2 = parse_audit("Status: incomplete\nIntegrity: clean\nContract audit: unknown\n")
    assert v2 and not audit_accepts(v2)
    assert parse_audit("no header here") is None



# ---------------------------------------------------------------- 逐行追加写文件
from terminus2_patches.helpers import AppendStreak, appended_files


def test_appended_files_finds_echo_and_printf_appends_only():
    assert appended_files("echo 'import sys' >> /app/port.py\n") == {"/app/port.py"}
    assert appended_files('printf "%s\\n" "x = 1" >>"out.txt"\n') == {"out.txt"}
    assert appended_files("echo a >> f1; echo b >> f2 && ls\n") == {"f1", "f2"}
    assert appended_files('echo "a >> b" >> real.txt\n') == {"real.txt"}          # 引号里的 >> 不算
    assert appended_files("cat >> notes.md << 'EOF'\necho x >> nope\nEOF\n") == set()   # heredoc 整块写入不算
    assert appended_files("python3 gen.py >> log.txt\n") == set()
    assert appended_files("echo done\n") == set()


def test_append_streak_counts_consecutive_turns_per_file():
    s = AppendStreak()
    assert s.observe(["echo a >> p.py\n"]) == {"p.py": 1}
    assert s.observe(["echo b >> p.py\n", "ls\n"]) == {"p.py": 2}
    assert s.observe(["echo c >> p.py\n", "echo x >> q.txt\n"]) == {"p.py": 3, "q.txt": 1}
    assert s.observe(["python3 p.py\n"]) == {}                                      # 中断就清零
    assert s.observe(["echo d >> p.py\n"]) == {"p.py": 1}


# ---- 闭环第 2 轮：固定触发条件 + 提醒文字（D-089）
from terminus2_patches.helpers import NoteTriggers, last_error_line, render_note  # noqa: E402


def test_repeat_command_fires_at_3_and_6_and_waiting_resets_it():
    t = NoteTriggers(100)
    fired = [t.observe(i, ["curl -s localhost:8000/health\n"], "") for i in range(1, 7)]
    assert [("repeat_command" in f) for f in fired] == [False, False, True, False, False, True]
    t.observe(7, [""], "")                                             # 只是在等：清零
    assert "repeat_command" not in t.observe(8, ["curl -s localhost:8000/health\n"], "")


def test_same_error_ignores_numbers_and_needs_three_turns_in_a_row():
    out = lambda n: f'  File "app.py", line {n}, in <module>\nNameError: name x is not defined'
    assert last_error_line(out(12)) == last_error_line(out(40))
    t = NoteTriggers(100)
    seq = [t.observe(i, [f"python3 app.py  # try {i}\n"], out(i)) for i in range(1, 4)]
    assert "same_error" in seq[2] and "same_error" not in seq[1]
    assert "same_error" not in t.observe(4, ["ls\n"], "app.py")          # 没报错：清零


def test_turn_budget_fires_once_at_half_and_once_at_80_percent():
    t = NoteTriggers(100)
    hits = [i for i in range(1, 101) if "turn_budget" in t.observe(i, ["ls\n"], "")]
    assert hits == [50, 80]


def test_append_streak_reports_files_and_render_fills_placeholders():
    t = NoteTriggers(100)
    f = {}
    for i in range(1, 4):
        f = t.observe(i, [f"echo 'line {i}' >> /app/out.py\n"], "")
    assert f["append_streak"] == {"n": 3, "files": ["/app/out.py"]}
    assert render_note("Stop appending to {files} ({n} turns).", f["append_streak"]) == \
        "[harness] Stop appending to /app/out.py (3 turns)."
