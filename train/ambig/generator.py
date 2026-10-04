"""合成“题面缺约定、环境里有证据”的训练题（2026-09-26）。

每道题 = 一个简单的数据处理任务 + 题面不写某个约定（日期格式、分隔符、金额单位、字段命名、排序、区间开闭、缺失值处理）
+ 约定写在工作区的某个文件里（配置、测试、示例输出、文档）+ 若干无关文件。
needs_evidence=False 的“清晰版”在题面里直接写明约定，作对照（学到的应是“缺约定时去查”，不是“永远翻遍所有文件”）。
答案唯一：只有按证据里的约定做才对；不查证据时猜中的概率约为 1/候选数。
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta


@dataclass
class Task:
    task_id: str
    family: str
    needs_evidence: bool
    instruction: str
    files: dict[str, str]
    answer: str
    answer_kind: str = "text"          # text | json
    evidence_path: str | None = None
    convention: str = ""
    meta: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


NAMES = ["ada", "grace", "alan", "edsger", "barbara", "ken", "dennis", "linus", "margaret", "tim", "radia", "donald",
         "john", "frances", "leslie", "yann", "fei", "andrew", "geoffrey", "judea"]
PROJECTS = ["billing", "reporting", "inventory", "analytics", "crm", "ledger", "scheduler", "notifier"]
FILLER_FILES = {
    "README.md": "# {proj}\n\nInternal service for the {proj} team. See docs/ for design notes.\n",
    "Makefile": "test:\n\tpytest -q\n\nlint:\n\truff check .\n",
    "docs/CHANGELOG.md": "## 1.4.0\n- performance improvements\n- dependency bumps\n\n## 1.3.2\n- fixed typo in logs\n",
    "src/utils.py": "def chunk(xs, n):\n    return [xs[i:i + n] for i in range(0, len(xs), n)]\n",
    ".gitignore": "__pycache__/\n*.pyc\n.venv/\n",
    "docs/ONCALL.md": "Pager rotation lives in the team wiki. Escalate after 15 minutes.\n",
}


HARD_FILLERS = {
    "tests/test_utils.py": "from src.utils import chunk\n\n\ndef test_chunk():\n    assert chunk([1, 2, 3], 2) == [[1, 2], [3]]\n",
    "config/logging.yaml": "version: 1\nroot:\n  level: INFO\n  handlers: [console]\n",
    "src/main.py": "import sys\n\n\ndef main(argv):\n    print(\"{proj}\", argv)\n\n\nif __name__ == \"__main__\":\n    main(sys.argv[1:])\n",
    "src/io_helpers.py": "def read_lines(path):\n    with open(path) as f:\n        return [l.rstrip(\"\\n\") for l in f]\n",
    "docs/architecture.md": "# Architecture\n\nThe {proj} service is a batch job. Inputs are CSV/JSON files; outputs go to downstream consumers.\n",
    "scripts/run.sh": "#!/bin/sh\npython -m src.main \"$@\"\n",
    "pyproject.toml": "[project]\nname = \"{proj}\"\nversion = \"1.4.0\"\n",
}

# 难版：证据改放到中性路径（路径里不再出现“importer / billing / leaderboard”这类与题面呼应的词），只能靠读内容找到
NEUTRAL = {".yaml": "config/settings.yaml", ".yml": "config/settings.yaml", ".ini": "config/settings.ini", ".md": "docs/notes.md",
           ".json": "fixtures/sample.json", ".txt": "fixtures/sample_output.txt", ".ts": "web/src/models.ts"}


def _neutral_path(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    ext = "." + base.rsplit(".", 1)[-1] if "." in base else ""
    if ext == ".py":
        return "tests/test_core.py" if base.startswith("test") else "src/core.py"
    return NEUTRAL.get(ext, "docs/notes.md")


def _fillers(rng: random.Random, proj: str, k: int = 3, hard: bool = False) -> dict[str, str]:
    pool = {**FILLER_FILES, **(HARD_FILLERS if hard else {})}
    keys = rng.sample(sorted(pool), k)
    return {p: pool[p].replace("{proj}", proj) for p in keys}


def _place(rng: random.Random, kinds: list[tuple[str, str]]) -> tuple[str, str]:
    """从候选 (路径, 证据形态) 里随机挑一个证据位置。"""
    return rng.choice(kinds)


# ---------------------------------------------------------------- families
def fam_date_format(rng, proj, needs):
    fmts = [("%Y-%m-%d", "YYYY-MM-DD"), ("%d/%m/%Y", "DD/MM/YYYY"), ("%m-%d-%Y", "MM-DD-YYYY"), ("%Y%m%d", "YYYYMMDD"),
            ("%d.%m.%Y", "DD.MM.YYYY")]
    fmt, label = rng.choice(fmts)
    start = date(2023, 1, 1) + timedelta(days=rng.randint(0, 700))
    days = sorted({start + timedelta(days=rng.randint(0, 400)) for _ in range(6)})
    # 保证日、月都 ≤ 12 以外的也有，避免 DD/MM 与 MM/DD 碰巧相同
    data = "id,created\n" + "".join(f"{i + 1},{d.isoformat()}\n" for i, d in enumerate(days))
    ans = "\n".join(d.strftime(fmt) for d in days)
    ex = days[0]
    path, kind = _place(rng, [(f"services/{proj}/config.yaml", "config"), (f"tests/test_{proj}_export.py", "test"),
                              ("examples/expected_export.txt", "example")])
    ev = {"config": f"service: {proj}\nexport:\n  date_format: \"{fmt}\"   # {label}\n  encoding: utf-8\n",
          "test": f"from export import format_date\n\n\ndef test_format_date():\n    assert format_date(\"{ex.isoformat()}\") == \"{ex.strftime(fmt)}\"\n",
          "example": f"# expected output of the export (first line)\n{ex.strftime(fmt)}\n..."}[kind]
    stated = f" The {proj} service expects dates as {label}." if not needs else ""
    instr = (f"Convert every date in data.csv to the date format the {proj} export expects and submit them one per line, "
             f"in the same order as the file.{stated}")
    return dict(files={"data.csv": data, path: ev}, answer=ans, evidence_path=path, convention=label, instruction=instr)


def fam_delimiter(rng, proj, needs):
    delims = [(",", "comma"), (";", "semicolon"), ("|", "pipe"), ("\t", "tab")]
    d, label = rng.choice(delims)
    rows = [{"name": n, "qty": rng.randint(1, 40)} for n in rng.sample(NAMES, 4)]
    ans = "\n".join([d.join(["name", "qty"])] + [d.join([r["name"], str(r["qty"])]) for r in rows])
    path, kind = _place(rng, [(f"importer/README.md", "doc"), (f"importer/settings.ini", "config"),
                              ("examples/import_sample.txt", "example")])
    shown = {"tab": "\\t (tab)"}.get(label, repr(d))
    ev = {"doc": f"# importer\n\nThe importer reads a header row followed by data rows and splits columns on {shown}.\n",
          "config": f"[import]\ncolumn_separator = {label}\nheader = true\n",
          "example": d.join(["name", "qty"]) + "\n" + d.join(["example", "3"]) + "\n"}[kind]
    stated = f" Use {label} as the column separator." if not needs else ""
    instr = (f"Export the records in records.json as a table (header row `name` and `qty`, then one row per record, same order) "
             f"in the format the importer reads, and submit it.{stated}")
    return dict(files={"records.json": json.dumps(rows, indent=2) + "\n", path: ev}, answer=ans, evidence_path=path,
                convention=label, instruction=instr)


def fam_amount_units(rng, proj, needs):
    from decimal import ROUND_HALF_UP, Decimal
    amts = [Decimal(f"{rng.uniform(1, 90):.2f}") for _ in range(5)]
    total = sum(amts)  # 精确到分，不经过浮点
    opts = [("cents", str(int(total * 100))), ("dollars_2dp", f"{total:.2f}"),
            ("dollars_int", str(int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))))]
    label, ans = rng.choice(opts)
    desc = {"cents": "integer amount in cents", "dollars_2dp": "decimal amount in dollars with exactly two decimals",
            "dollars_int": "whole dollars, rounded to the nearest dollar"}[label]
    path, kind = _place(rng, [("api/schema.json", "schema"), (f"tests/test_{proj}_total.py", "test")])
    ev = {"schema": json.dumps({"type": "object", "properties": {"total": {"type": "integer" if label != "dollars_2dp" else "string",
                                                                         "description": desc}}}, indent=2) + "\n",
          "test": f"def test_total_format():\n    # the API field `total` is an {desc}\n    assert format_total(12.5) == "
                  f"{json.dumps({'cents': '1250', 'dollars_2dp': '12.50', 'dollars_int': '13'}[label])}\n"}[kind]
    stated = f" The billing API expects the total as follows: {desc}." if not needs else ""
    instr = (f"Compute the total of all amounts in transactions.csv and submit the value of the billing API's `total` field "
             f"in the form the API expects.{stated}")
    data = "id,amount\n" + "".join(f"{i + 1},{a:.2f}\n" for i, a in enumerate(amts))
    return dict(files={"transactions.csv": data, path: ev}, answer=ans, answer_kind="scalar_or_total", evidence_path=path,
                convention=label, instruction=instr)


def fam_key_case(rng, proj, needs):
    first, last = rng.sample(NAMES, 2)
    signup = (date(2024, 1, 1) + timedelta(days=rng.randint(0, 300))).isoformat()
    cases = {"camelCase": ["firstName", "lastName", "signupDate"], "snake_case": ["first_name", "last_name", "signup_date"],
             "PascalCase": ["FirstName", "LastName", "SignupDate"], "kebab-case": ["first-name", "last-name", "signup-date"]}
    label = rng.choice(sorted(cases))
    keys = cases[label]
    ans = json.dumps(dict(zip(keys, [first.title(), last.title(), signup])), sort_keys=True)
    path, kind = _place(rng, [("frontend/src/types.ts", "types"), ("examples/sample_user.json", "example")])
    ev = {"types": "export interface User {\n" + "".join(f"  \"{k}\": string;\n" for k in keys) + "}\n",
          "example": json.dumps(dict(zip(keys, ["Jane", "Doe", "2024-01-01"])), indent=2) + "\n"}[kind]
    stated = f" The frontend uses {label} field names ({', '.join(keys)})." if not needs else ""
    instr = (f"Submit a JSON object for the user {first.title()} {last.title()} (signed up {signup}) with their first name, "
             f"last name and signup date, using the field names the frontend expects.{stated}")
    return dict(files={path: ev}, answer=ans, answer_kind="json", evidence_path=path, convention=label, instruction=instr)


def fam_sort_order(rng, proj, needs):
    names = rng.sample(NAMES, 5)
    scores = rng.sample(range(10, 99), 5)
    rows = list(zip(names, scores))
    orders = {"score_desc": sorted(rows, key=lambda r: -r[1]), "score_asc": sorted(rows, key=lambda r: r[1]),
              "name_asc": sorted(rows, key=lambda r: r[0]), "name_desc": sorted(rows, key=lambda r: r[0], reverse=True)}
    label = rng.choice(sorted(orders))
    ans = "\n".join(r[0] for r in orders[label])
    desc = {"score_desc": "by score, highest first", "score_asc": "by score, lowest first",
            "name_asc": "alphabetically by name (A to Z)", "name_desc": "reverse alphabetically by name (Z to A)"}[label]
    path, kind = _place(rng, [("docs/leaderboard.md", "doc"), ("tests/test_leaderboard.py", "test")])
    top2 = [r[0] for r in orders[label][:2]]
    ev = {"doc": f"# Leaderboard\n\nThe leaderboard lists players {desc}.\n",
          "test": f"def test_order(board):\n    # players are listed {desc}\n    assert board.names()[:2] == {top2!r}\n"}[kind]
    stated = f" The leaderboard lists players {desc}." if not needs else ""
    instr = f"Submit the players from scores.csv in the order the leaderboard shows them, one name per line.{stated}"
    data = "name,score\n" + "".join(f"{n},{s}\n" for n, s in rows)
    return dict(files={"scores.csv": data, path: ev}, answer=ans, evidence_path=path, convention=label, instruction=instr)


def fam_range_boundary(rng, proj, needs):
    lo, hi = 10, 20
    vals = [lo, hi, lo, hi] + [rng.randint(0, 30) for _ in range(8)]
    rng.shuffle(vals)
    rules = {"[lo,hi]": lambda v: lo <= v <= hi, "[lo,hi)": lambda v: lo <= v < hi, "(lo,hi]": lambda v: lo < v <= hi,
             "(lo,hi)": lambda v: lo < v < hi}
    label = rng.choice(sorted(rules))
    ans = str(sum(1 for v in vals if rules[label](v)))
    desc = {"[lo,hi]": "both bounds inclusive", "[lo,hi)": "lower bound inclusive, upper bound exclusive",
            "(lo,hi]": "lower bound exclusive, upper bound inclusive", "(lo,hi)": "both bounds exclusive"}[label]
    path, kind = _place(rng, [("alerts/rules.py", "code"), ("alerts/README.md", "doc")])
    ev = {"code": f"def in_alert_window(v, lo={lo}, hi={hi}):\n    \"\"\"Alert window check: {desc}.\"\"\"\n    raise NotImplementedError\n",
          "doc": f"# Alerts\n\nA reading is inside the alert window when it lies between {lo} and {hi} ({desc}).\n"}[kind]
    stated = f" The alert window is {desc}." if not needs else ""
    instr = f"Count how many readings in readings.txt fall inside the alert window between {lo} and {hi} and submit the count.{stated}"
    return dict(files={"readings.txt": "\n".join(map(str, vals)) + "\n", path: ev}, answer=ans, evidence_path=path,
                convention=label, instruction=instr)


def fam_missing(rng, proj, needs):
    vals = [round(rng.uniform(1, 50), 1) for _ in range(7)]
    miss_idx = set(rng.sample(range(7), 2))
    cells = ["" if i in miss_idx else f"{v}" for i, v in enumerate(vals)]
    present = [v for i, v in enumerate(vals) if i not in miss_idx]
    opts = {"skip": sum(present) / len(present), "zero": sum(present) / len(vals)}
    label = rng.choice(sorted(opts))
    ans = f"{opts[label]:.2f}"
    desc = {"skip": "missing readings are skipped (not counted)", "zero": "missing readings count as 0"}[label]
    path, kind = _place(rng, [("dashboard/config.yaml", "config"), ("dashboard/README.md", "doc")])
    ev = {"config": f"average:\n  missing: {label}   # {desc}\n  round: 2\n",
          "doc": f"# Dashboard\n\nThe average uses two decimals; {desc}.\n"}[kind]
    stated = f" On the dashboard, {desc}." if not needs else ""
    instr = f"Compute the average reading in sensor.csv the way the dashboard does, rounded to 2 decimals, and submit it.{stated}"
    data = "t,reading\n" + "".join(f"{i},{c}\n" for i, c in enumerate(cells))
    return dict(files={"sensor.csv": data, path: ev}, answer=ans, evidence_path=path, convention=label, instruction=instr)


FAMILIES = {"date_format": fam_date_format, "delimiter": fam_delimiter, "amount_units": fam_amount_units,
            "key_case": fam_key_case, "sort_order": fam_sort_order, "range_boundary": fam_range_boundary,
            "missing": fam_missing}


def make_task(seed: int, family: str | None = None, needs_evidence: bool | None = None, difficulty: str = "easy") -> Task:
    """difficulty=hard：同一 seed 下数据与约定完全相同，只是证据换到中性路径、无关文件更多（8 个）→ 与 easy 逐题配对。"""
    rng = random.Random(seed)
    fam = family or rng.choice(sorted(FAMILIES))
    needs = rng.random() < 0.75 if needs_evidence is None else needs_evidence
    proj = rng.choice(PROJECTS)
    spec = FAMILIES[fam](rng, proj, needs)
    fill_rng = random.Random(seed * 7 + 1)   # 填充文件单独的随机流，保证 easy/hard 的数据与约定不受影响
    hard = difficulty == "hard"
    ev = spec["evidence_path"]
    task_files = dict(spec["files"])
    if hard:
        new_ev = _neutral_path(ev)
        task_files[new_ev] = task_files.pop(ev)
        ev = new_ev
    files = {**_fillers(fill_rng, proj, k=8 if hard else 3, hard=hard), **task_files}
    return Task(task_id=f"{fam}-{seed}" + ("-hard" if hard else ""), family=fam, needs_evidence=needs, instruction=spec["instruction"],
                files=files, answer=spec["answer"], answer_kind=spec.get("answer_kind", "text"), evidence_path=ev,
                convention=spec["convention"], meta={"project": proj, "difficulty": difficulty})


def check_answer(task: Task, submitted: str) -> bool:
    s = (submitted or "").replace("\r\n", "\n").strip()
    if task.answer_kind == "scalar_or_total":
        # 接受纯数值，或 schema 形状的 {"total": v}（证据文件本身就是这个形状）
        try:
            obj = json.loads(s)
            if isinstance(obj, dict) and set(obj) == {"total"}:
                s = str(obj["total"])
        except Exception:  # noqa: BLE001
            pass
        return s.strip().strip('"') == task.answer
    if task.answer_kind == "json":
        try:
            return json.loads(s) == json.loads(task.answer)
        except Exception:  # noqa: BLE001
            return False
    norm = lambda x: "\n".join(line.rstrip() for line in x.strip().split("\n"))
    return norm(s) == norm(task.answer)


def make_split(n: int, seed0: int, needs_evidence: bool | None = None, difficulty: str = "easy") -> list[Task]:
    """seed0 区分 train / heldout，保证两边 seed 不重叠；difficulty 相同 seed 下可配对。"""
    return [make_task(seed0 + i, needs_evidence=needs_evidence, difficulty=difficulty) for i in range(n)]


if __name__ == "__main__":
    import sys
    for t in make_split(int(sys.argv[1]) if len(sys.argv) > 1 else 3, 1000):
        print(json.dumps(t.to_json(), indent=1)[:1500]); print("-" * 60)
