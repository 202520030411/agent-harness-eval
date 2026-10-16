"""纯函数：命令分类、卡死检测、审计报告解析。不依赖 harbor，可单测。"""
from __future__ import annotations

import json
import re

WRITE_CMD_RE = re.compile(r"(>\s*\S|>>|\bsed\s+-i|\btee\b|\bmv\b|\bcp\b|\brm\b|\btouch\b|\bmkdir\b|\bchmod\b|\bchown\b|"
                          r"pip3?\s+install|apt(-get)?\s+install|\bmake\b|\bcmake\b|\bgit\s+(commit|push|reset|checkout|rebase|merge|stash)\b|"
                          r"\bpython3?\s+-\s*<<|\bcat\s*<<|<<\s*['\"]?EOF|\bnpm\s+install|\bcargo\s+build|\bdd\b)")
INTERACTIVE_PROMPT_RE = re.compile(
    r"(\[y/N\]|\[Y/n\]|\(y/n\)|\(yes/no\)|Password:|password for|--More--|\(END\)|Press RETURN|Press any key|"
    r"Do you want to continue\?|^:\s*$|^>>>\s*$|^>\s*$)", re.MULTILINE | re.IGNORECASE)   # 整行只有 : / >>> / > 才算提示符
EDITOR_PAGER_RE = re.compile(r"^\s*(vim?|nvim|nano|emacs|less|more|top|htop|man|ssh|telnet|ftp|gdb|tmux|screen)(\s|$)")
BARE_REPL_RE = re.compile(r"^\s*(python3?|ipython|node|irb|psql|mysql|sqlite3|bash|sh)\s*(-i\s*)?$")   # 只有裸调用才是交互 REPL
SHELL_PROMPT_TAIL_RE = re.compile(r"(\$|#|\])\s*$")


def is_simple_command(keystrokes: str) -> bool:
    """能安全地在末尾追加 '; tmux wait -S <ch>' 的命令：单行、以换行结束、无 heredoc、不后台、不是交互程序。"""
    if not keystrokes.endswith("\n") or keystrokes.count("\n") != 1:
        return False
    body = keystrokes.rstrip("\n")
    if not body.strip() or "<<" in body or body.rstrip().endswith("&") or body.rstrip().endswith("\\"):
        return False
    if EDITOR_PAGER_RE.match(body) or BARE_REPL_RE.match(body):
        return False
    return True


def is_write_command(keystrokes: str) -> bool:
    """这条 keystrokes 会改文件。引号里的 > 、2>/dev/null、2>&1 这类只改输出去向的写法不算（2026-10-12 修，D-085）。"""
    body = "\n".join(_FD_REDIRECT_RE.sub(" ", _blank_quotes(line)) for line in _drop_heredoc_bodies(keystrokes).split("\n"))
    return bool(WRITE_CMD_RE.search(body))


def detect_interactive_prompt(screen_tail: str) -> str | None:
    m = INTERACTIVE_PROMPT_RE.search(screen_tail.rstrip()[-200:])
    return m.group(0) if m else None


class StuckTracker:
    """连续相同 keystrokes 的计数（OpenHands StuckDetector 的最简版）。"""

    def __init__(self) -> None:
        self.last: tuple[str, ...] | None = None
        self.streak = 0
        self.reminders = 0

    def observe(self, keystrokes: list[str]) -> int:
        sig = tuple(k.strip() for k in keystrokes if k.strip())
        if not sig:
            return self.streak
        if sig == self.last:
            self.streak += 1
        else:
            self.last, self.streak = sig, 1
        return self.streak


def extract_json_fields(content: str, fields: tuple[str, ...]) -> dict:
    """从模型回复里取出我们新增的 JSON 字段（requirements / ambiguities）。取不到就空。"""
    try:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            return {}
        data = json.loads(content[start:end + 1])
    except Exception:
        return {}
    out = {}
    for f in fields:
        v = data.get(f)
        if v:
            out[f] = v
    return out


AUDIT_STATUS_RE = re.compile(r"^\s*Status:\s*(complete|incomplete|blocked)\s*$", re.M | re.I)
AUDIT_INTEGRITY_RE = re.compile(r"^\s*Integrity:\s*(clean|suspect|violation)\s*$", re.M | re.I)
AUDIT_CONTRACT_RE = re.compile(r"^\s*Contract audit:\s*(aligned|unknown|needs_revision|invalid)\s*$", re.M | re.I)


def parse_audit(text: str) -> dict | None:
    a, b, c = AUDIT_STATUS_RE.search(text), AUDIT_INTEGRITY_RE.search(text), AUDIT_CONTRACT_RE.search(text)
    if not (a and b and c):
        return None
    return {"status": a.group(1).lower(), "integrity": b.group(1).lower(), "contract": c.group(1).lower(), "raw": text}


def audit_accepts(v: dict) -> bool:
    return v["status"] == "complete" and v["integrity"] == "clean" and v["contract"] == "aligned"


_PATH_RE = re.compile(r"(?<![\w/])(/app/[\w][\w./-]*[\w])")
_NAMED_RE = re.compile(r"(?:called|named|titled|to|into|at|program|script)\s+[`\"']?([\w-]+\.(?:txt|json|py|js|c|cpp|sh|fasta|md|csv|yaml|yml|toml|html|tex|pdf|png|ppm))[`\"']?", re.I)


def extract_deliverables(instruction: str, max_n: int = 4) -> list[str]:
    """第二圈闭环用：题面里提到的输出文件路径（交付物）。只认 /app/ 下的绝对路径和“called/named/to X.ext”句式；去掉明显是输入的（题面说 provided/given 的）。"""
    found: list[str] = []
    for m in _PATH_RE.finditer(instruction):
        p = m.group(1).rstrip(".,;:")
        if p.endswith("/") or "*" in p: continue
        found.append(p)
    for m in _NAMED_RE.finditer(instruction):
        found.append("/app/" + m.group(1))
    # 输入文件：题面说 “provided a file X” / “given ... X” 的不算交付物
    given = set()
    for m in re.finditer(r"(?:provided|given|contains|existing)\b[^.\n]{0,80}?([\w-]+\.[a-z]{1,5})", instruction, re.I):
        given.add(m.group(1).lower())
    out = []
    for p in found:
        if p.split("/")[-1].lower() in given: continue
        if p not in out: out.append(p)
    return out[:max_n]


# ---------------------------------------------------------------- H1 / H2（Qwen 阶段 0 的毛病）
# 运行时的交卷把关与离线统计（tools/qwen_bp_rules.py）共用这几个函数，保证两边口径一致。

# 不算“运行了东西”的命令：只显示内容的、只改文件的、装包的、git。其余（python3、pytest、./a.out、make、gcc、curl、diff、grep …）都算。
NON_RUN_HEADS = frozenset({
    "echo", "printf", "cat", "ls", "ll", "head", "tail", "less", "more", "wc", "pwd", "cd", "clear", "reset", "true", "sleep",
    "file", "stat", "tree", "which", "type", "whoami", "id", "date", "history", "du", "df", "find", "export", "source", ".",
    "set", "unset", "alias", "ps", "jobs", "kill", "pkill", "killall", "uname", "env", "printenv", "nproc", "free", "man", "exit",
    "mv", "cp", "rm", "rmdir", "touch", "mkdir", "chmod", "chown", "ln", "tee", "sed", "awk",
    "pip", "pip3", "apt", "apt-get", "apk", "yum", "dnf", "conda", "git"})
_PREFIX_TOKENS = frozenset({"sudo", "time", "nohup", "env", "then", "do", "else", "!"})
_HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([\w.-]+)\1")   # <<< 是 here-string，不是 heredoc
_SPLIT_RE = re.compile(r"&&|\|\||;|\||\n")
ADMIT_RE = re.compile(r"(haven't|have not|hasn't|couldn't|could not|unable to|not (yet )?(been )?able|still not|not meeting|doesn't meet|don't meet|"
                      r"did not (succeed|work|pass)|didn't (succeed|work|pass)|placeholder|dummy value|although|while (we|i) (couldn't|could not|haven't|were unable|was unable)|"
                      r"difficult(y|ies) with|not (fully|completely) (eliminate|solve|meet|pass))", re.I)


def _quoted_spans(line: str) -> list[tuple[int, int]]:
    """一行里单引号、双引号包住的区间（双引号里的反斜杠转义算进去）。没配对的引号一直算到行尾。"""
    spans, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in "'\"":
            j = i + 1
            while j < n and line[j] != c:
                j += 2 if (c == '"' and line[j] == "\\") else 1
            spans.append((i, min(j, n)))
            i = j + 1
        else:
            i += 1
    return spans


def _heredoc_marker(line: str):
    """这一行里真正的 heredoc 起始标记（<<EOF / << 'EOF'）；引号里面的 << 不算（例如 echo 'cout << x' >> f.cpp）。"""
    spans = _quoted_spans(line)
    for m in _HEREDOC_RE.finditer(line):
        if not any(a < m.start() < b for a, b in spans):
            return m
    return None


def strip_heredoc_bodies(keystrokes: str) -> str:
    """去掉 heredoc 正文（<<EOF 到结束标记之间的行）：正文是写进文件的内容，不是在 shell 里执行的命令。
    标记所在的行从标记处截断（只保留前面的命令）。"""
    out, end = [], None
    for line in keystrokes.split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        m = _heredoc_marker(line)
        if m:
            end, line = m.group(2), line[:m.start()]
        out.append(line)
    return "\n".join(out)


def _drop_heredoc_bodies(keystrokes: str) -> str:
    """同上，但标记所在的行完整保留（cat << 'EOF' > out.py 后半截的重定向也要看到）。"""
    out, end = [], None
    for line in keystrokes.split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        m = _heredoc_marker(line)
        if m:
            end = m.group(2)
        out.append(line)
    return "\n".join(out)


def _blank_quotes(line: str) -> str:
    """把引号里的内容清空（保留一对空引号），引号里的 > 、<< 不再被当成重定向。"""
    out, last = [], 0
    for a, b in _quoted_spans(line):
        out.append(line[last:a + 1])
        last = b
    out.append(line[last:])
    return "".join(out)


# 只改输出去向、不写任何文件的重定向：2>/dev/null、>/dev/null、&>/dev/null、2>&1、>&2
_FD_REDIRECT_RE = re.compile(r"&>>?\s*/dev/null|\d*>>?\s*/dev/null|\d*>&\d+-?")


def command_heads(keystrokes: str) -> list[str]:
    """一条 keystrokes 里每个子命令的第一个词（按 && || ; | 换行拆；跳过 VAR=x、sudo、timeout N 这类前缀）。"""
    heads = []
    unquoted = "\n".join(_blank_quotes(line) for line in strip_heredoc_bodies(keystrokes).split("\n"))   # 引号里的 ; | 不拆
    for part in _SPLIT_RE.split(unquoted):
        toks = [t.lstrip("({") for t in part.strip().split()]
        toks = [t for t in toks if t]
        while toks and (re.match(r"^\w+=", toks[0]) or toks[0] in _PREFIX_TOKENS):
            toks = toks[1:]
        if toks and toks[0] == "timeout" and len(toks) > 2:
            toks = toks[2:]
        if toks and not toks[0].startswith("#"):
            heads.append(toks[0])
    return heads


def is_run_command(keystrokes: str) -> bool:
    """这条 keystrokes 真正运行了东西（至少一个子命令不在 NON_RUN_HEADS 里）。按键（C-c）和空等待不算。"""
    ks = keystrokes.strip()
    if not ks or re.fullmatch(r"C-[a-z]", ks):
        return False
    return any(h not in NON_RUN_HEADS for h in command_heads(ks))


def no_run_after_last_write(executed: list[str]) -> bool:
    """H2 触发条件 1：最后一次改文件之后，没有再运行过任何东西（只 echo / cat / ls 过）。
    一条命令既写又跑（python3 gen.py > out.txt）算“写完后跑过”。"""
    seq = []
    for ks in executed:
        if is_write_command(ks):
            seq.append("W")
        if is_run_command(ks):
            seq.append("R")
    last_w = max((i for i, k in enumerate(seq) if k == "W"), default=-1)
    last_r = max((i for i, k in enumerate(seq) if k == "R"), default=-1)
    return last_w >= 0 and last_r < last_w


def admission_quote(text: str, max_len: int = 240) -> str | None:
    """H2 触发条件 2：宣布完成那一轮的 analysis / plan 里承认没做成，返回所在的那句话（没有就 None）。"""
    m = ADMIT_RE.search(text or "")
    if not m:
        return None
    start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
    ends = [i for i in (text.find(".", m.end()), text.find("\n", m.end())) if i >= 0]
    end = min(ends) + 1 if ends else len(text)
    return text[start:end].strip()[:max_len]


def ends_in_continuation_prompt(terminal_output: str) -> bool:
    """终端最后一行只有 '>'：shell 在等一条没写完的命令（引号没闭合 / heredoc 没有结束标记）。"""
    lines = [l for l in (terminal_output or "").rstrip().splitlines() if l.strip()]
    return bool(lines) and lines[-1].strip() == ">"


# ---------------------------------------------------------------- 逐行追加写文件（闭环第 1 轮发现，见 experiments/loop/README.md）
_TOKEN_RE = re.compile(r"""'[^']*'|"(?:[^"\\]|\\.)*"|>>|&&|\|\||[;|\n]|[^\s'";|&<>]+|[<>&]""")
_SEPARATORS = frozenset({";", "&&", "||", "|", "\n"})


def appended_files(keystrokes: str) -> set[str]:
    """这一轮里用 echo / printf 加 >> 追加过的文件。引号里的 >> 不算，heredoc 正文不算，cat >> f << EOF 不算（那是整块写入）。"""
    out: set[str] = set()
    head, want = None, False
    for tok in _TOKEN_RE.findall(strip_heredoc_bodies(keystrokes)):
        if tok in _SEPARATORS:
            head, want = None, False
        elif want:
            out.add(tok.strip("'\"").rstrip(")}"))
            want = False
        elif head is None:
            t = tok.lstrip("({")
            if t and t not in _PREFIX_TOKENS and not re.match(r"^\w+=", t):   # 跳过 sudo、VAR=x、(、循环里的 do
                head = t
        elif tok == ">>" and head in ("echo", "printf"):
            want = True
    return out


class AppendStreak:
    """每个文件连续被逐行追加了几轮；某一轮没追加它就清零。"""

    def __init__(self) -> None:
        self.streak: dict[str, int] = {}

    def observe(self, keystrokes: list[str]) -> dict[str, int]:
        files: set[str] = set()
        for k in keystrokes:
            files |= appended_files(k)
        self.streak = {f: self.streak.get(f, 0) + 1 for f in files}
        return self.streak


# ---------------------------------------------------------------- 闭环可用的提醒触发条件（D-089）
# 提议模型只能从这里挑一个条件、再写一句话；条件本身是固定的程序，提议模型改不了，也看不到题目内容。
NOTE_TRIGGERS: dict[str, str] = {
    "append_streak": "the same file was appended to with echo/printf >> in 3 executed turns in a row (fires again at 10)",
    "repeat_command": "the exact same non-empty command batch was sent in 3 turns in a row (fires again at 6)",
    "same_error": "the same error line (Traceback / error: / No such file / command not found / Permission denied) ended the "
                  "output of 3 turns in a row (fires again at 6)",
    "turn_budget": "half of the turn limit has been used (fires once; once more at 80%)",
}
NOTE_FIRE_AT = {"append_streak": (3, 10), "repeat_command": (3, 6), "same_error": (3, 6)}
NOTE_PLACEHOLDERS = ("n", "files")          # 提醒文字里只能用 {n}（计数 / 轮次）和 {files}（append_streak 的文件名）
NOTE_MAX_PER_TRIAL = 3                      # 每条提醒每个 trial 最多发几次
# \w*error 同时认 "error:"、"NameError"、"ModuleNotFoundError"（前面没有单词边界）
_ERROR_LINE_RE = re.compile(r"(Traceback \(most recent call last\)|\w*error\b|No such file or directory|command not found|"
                            r"Permission denied|\bfailed\b)", re.I)


def last_error_line(output: str) -> str | None:
    """输出里最后一行"像报错"的文字，数字换成 #（行号、进程号不同也算同一个错）。没有报错返回 None。"""
    for line in reversed((output or "").splitlines()):
        if _ERROR_LINE_RE.search(line):
            return re.sub(r"\d+", "#", line.strip())[:200]
    return None


class NoteTriggers:
    """每轮看一次本轮执行的命令和输出，返回本轮触发的条件 {名字: {"n": 计数, ...}}。每个 trial 新建一个。"""

    def __init__(self, max_turns: int) -> None:
        self.max_turns = max_turns
        self.append = AppendStreak()
        self.last_cmd: str | None = None
        self.cmd_streak = 0
        self.last_err: str | None = None
        self.err_streak = 0
        self.budget_fired: set[float] = set()

    def observe(self, turn: int, keystrokes: list[str], output: str) -> dict[str, dict]:
        fired: dict[str, dict] = {}
        streak = self.append.observe(keystrokes)
        hot = sorted(f for f, n in streak.items() if n in NOTE_FIRE_AT["append_streak"])
        if hot:
            fired["append_streak"] = {"n": max(streak[f] for f in hot), "files": hot}
        cmd = "\n".join(k.strip() for k in keystrokes if k.strip())
        # 空命令（只是在等）不算重复，也把计数清零
        self.cmd_streak = (self.cmd_streak + 1 if cmd == self.last_cmd else 1) if cmd else 0
        self.last_cmd = cmd or None
        if self.cmd_streak in NOTE_FIRE_AT["repeat_command"]:
            fired["repeat_command"] = {"n": self.cmd_streak}
        err = last_error_line(output)
        self.err_streak = (self.err_streak + 1 if err == self.last_err else 1) if err else 0
        self.last_err = err
        if self.err_streak in NOTE_FIRE_AT["same_error"]:
            fired["same_error"] = {"n": self.err_streak}
        for frac in (0.5, 0.8):
            if self.max_turns and turn >= frac * self.max_turns and frac not in self.budget_fired:
                self.budget_fired.add(frac)
                fired["turn_budget"] = {"n": turn}
        return fired


def render_note(text: str, info: dict) -> str:
    """把提醒文字里的 {n}、{files} 填上；其他花括号原样保留（scope 检查时已经拒绝了别的占位符）。"""
    out = text.replace("{n}", str(info.get("n", ""))).replace("{files}", ", ".join(info.get("files", [])) or "the file")
    return "[harness] " + out
