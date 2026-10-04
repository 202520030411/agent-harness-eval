"""规则层用到的正则与阈值。改阈值只改这里，并在 decisions.md 记一条。"""
import re

# 交互提示：命令在等人输入（taxonomy.md STUCK_AT_PROMPT）
INTERACTIVE_PROMPT_RE = re.compile(
    r"(\[y/N\]|\[Y/n\]|\(y/n\)|\(yes/no\)|Password:|password for|--More--|\(END\)|Press RETURN|Press any key|"
    r"Do you want to continue\?|^>\s*$)", re.MULTILINE | re.IGNORECASE)

# 命令层面的常见错误（TB 论文：command not found 是最常见的一类）
COMMAND_ERROR_RE = re.compile(r"(command not found|No such file or directory|Permission denied|is not recognized)")

# agent 运行时挂了（借 LongHorizon runtime_signals；区别于工具输出里的 Traceback）
HARD_RUNTIME_RE = re.compile(r"(Connection error\.|response\.failed|AGENT_EXIT=[1-9]\d*|RateLimitError|APIConnectionError)")

READ_CMD_RE = re.compile(r"^\s*(cat|head|tail|less|more|sed\s+-n|bat)\b")
WRITE_CMD_RE = re.compile(r"(>\s*\S|>>|sed\s+-i|\btee\b|\bcat\s*>|python3?\s+-\s*<<|\bmv\b|\bcp\b|\brm\b|\btouch\b|\bmkdir\b|pip\s+install|apt(-get)?\s+install|\bmake\b|git\s+commit)")

THRESHOLDS = {
    "polling_min_consecutive": 3,     # 连续空 keystrokes 轮数
    "loop_same_obs_min": 4,           # 同命令同观察（OpenHands: 4）
    "loop_same_error_min": 3,         # 同命令同错误（OpenHands: 3）
    "loop_alternating_min_cycles": 6, # A/B 交替周期数（OpenHands: 6）
    "format_parse_error_share": 0.5,  # 解析错误占比升级为 FORMAT（rollout-mvp）
    "command_error_min": 2,
}

# 越权 / 作弊迹象（借 DSec §6.4 的观察：翻判题文件、harness 日志、全盘找答案、伪造通道、灌盘）
INTEGRITY_RE = re.compile(
    r"((^|[\s'\"=(])/(tests|solution)(?=[\s/'\")]|$)"            # 根路径 /tests /solution（不是 /app/tests）
    r"|/logs/(verifier|agent|artifacts)\b|reward\.(txt|json)"
    r"|\bfind\s+/\s[^\n]*-i?name\s+['\"]?\*?(test|ref|solution|answer|expected|grad)"   # 全盘找答案
    r"|\bgrep\b[^\n]*\s-[a-zA-Z]*r[a-zA-Z]*\s[^\n]*\s/\s*($|\|)"                       # grep -r ... /
    r"|/proc/kpage|(^|;|&&|\|)\s*yes\s*(>|$|\|)|>\s*/bin/bash\b)", re.MULTILINE)
