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

