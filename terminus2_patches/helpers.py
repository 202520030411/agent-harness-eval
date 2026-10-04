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
    return bool(WRITE_CMD_RE.search(keystrokes))


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


def strip_heredoc_bodies(keystrokes: str) -> str:
    """去掉 heredoc 正文（<<EOF 到结束标记之间的行）：正文是写进文件的内容，不是在 shell 里执行的命令。"""
    out, end = [], None
    for line in keystrokes.split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        m = _HEREDOC_RE.search(line)
        if m:
            end, line = m.group(2), line[:m.start()]
        out.append(line)
    return "\n".join(out)


def command_heads(keystrokes: str) -> list[str]:
    """一条 keystrokes 里每个子命令的第一个词（按 && || ; | 换行拆；跳过 VAR=x、sudo、timeout N 这类前缀）。"""
    heads = []
    for part in _SPLIT_RE.split(strip_heredoc_bodies(keystrokes)):
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
