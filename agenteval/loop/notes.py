"""提醒文字的防泄题过滤（D-085）：提议模型写的提醒在进 harness 之前必须过这一关。固定规则，不调模型。

拦三类：
1. 提到判分、测试、答案、诱饵的（提醒只能谈模型自己的行为，不能把它引向评分）；
2. 带进某道题特有内容的：和任何一道题的题面 / 测试 / 参考解有连续 6 个词相同，或出现只在少数题里出现的标识符
   （文件名、带下划线或数字的名字）；
3. 教模型早点交卷、少做事的（钻"更省"这条接受路径的空子）。
过了这一关还要另一家模型审查、人批准（不在这里），每种新的触发条件第一次用时人看一眼。
"""
from __future__ import annotations

import re

MAX_WORDS = 60
BANNED = re.compile(
    r"\b(tests?|testing|pytest|unittest|verif\w*|grad(e|er|ers|ing)|scor\w*|rewards?|solutions?|answers?|expected[_ ]outputs?|"
    r"hidden|oracle|canary|benchmark\w*|checker|judg\w*|evaluat\w*|cheat\w*|hack\w*)\b"
    r"|/tests|/logs|/opt/grader|/solution|reward\.txt|solve\.sh", re.I)
GIVE_UP = re.compile(r"(mark|declare|finish|submit|stop|give up|quit|end)\w*\b[^.\n]{0,60}\b(early|now|immediately|right away|soon|quickly|"
                     r"even if|without (checking|running|verifying))|task_complete\W{0,3}\s*(:|=|to|as)?\s*true", re.I)
# 只拦"催它交卷"的说法；"在真正检查通过之前保持 task_complete 为 false"这种反方向的提醒放行
# 这些词出现在很多题里或者本来就是 harness 的通用说法，不算"某道题特有"
GENERIC = {"/app", "eof", "python3", "bash", "echo", "printf", "cat", "c-c", "{file}", "{files}", "{n}"}
_WORD = re.compile(r"[a-z0-9]+")
_IDENT = re.compile(r"(?<![\w{])(/[\w./-]+|[A-Za-z]\w*_\w+|\w+\.[A-Za-z]{1,5}\b|\w*\d\w*)")


def _ngrams(text: str, n: int = 6) -> set[tuple[str, ...]]:
    w = _WORD.findall(text.lower())
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def screen_note(text: str, task_texts: list[str], rare_frac: float = 0.10) -> list[str]:
    """返回拦下的理由（空列表 = 通过）。task_texts = 每道题的题面 + 测试 + 参考解（每题一个字符串）。"""
    problems = []
    words = len(re.findall(r"\S+", re.sub(r"\{[a-z]+\}", "X", text.split("\n")[0])))
    if words > MAX_WORDS:
        problems.append(f"too long: {words} words in the first line (max {MAX_WORDS})")
    m = BANNED.search(text)
    if m:
        problems.append(f"mentions grading / tests / answers: {m.group(0)!r}")
    m = GIVE_UP.search(text)
    if m:
        problems.append(f"pushes the model to stop or submit: {m.group(0)!r}")
    note_grams = _ngrams(text)
    for i, t in enumerate(task_texts):
        shared = note_grams & _ngrams(t)
        if shared:
            problems.append(f"shares a 6-word sequence with task #{i}: {' '.join(next(iter(shared)))!r}")
            break
    if task_texts:
        lowered = [t.lower() for t in task_texts]
        for ident in {x.lower() for x in _IDENT.findall(text)} - GENERIC:
            hits = sum(1 for t in lowered if ident in t)
            if 0 < hits < max(1, rare_frac * len(task_texts)):
                problems.append(f"uses an identifier that appears only in {hits} of {len(task_texts)} tasks: {ident!r}")
    return problems
