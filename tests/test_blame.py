"""归责二维表四象限各一个用例（DESIGN.md §2 blame.py 的验收）。"""
from agenteval.report.blame import blame_table
from agenteval.schemas import FailureLabel, Step, TrialRecord


def mk(task, passed, labels=()):
    t = TrialRecord(f"{task}-{len(labels)}", task, "c", 0, "j", "a", "m", 1.0 if passed else 0.0, "ok", None, None, 1, 0, 1.0, 0, 0, 0, 0.0, [Step(1, "agent")])
    t.labels = [FailureLabel(n, True, "BOOLEAN", "RULE", "NONE", "UNKNOWN", 1.0, "", None, None, "failure") for n in labels]
    return t


def arm(rate_by_pattern: dict[str, float], n=20):
    ts = []
    for i in range(n):
        labs = [p for p, r in rate_by_pattern.items() if i < round(r * n)]
        ts.append(mk(f"t{i}", not labs, labs))
    return ts


def test_four_quadrants():
    weak_base = arm({"HARNESS_ONLY": 0.5, "MODEL_ONLY": 0.5, "BOTH": 0.5, "NEITHER": 0.5})
    weak_mod = arm({"HARNESS_ONLY": 0.1, "MODEL_ONLY": 0.5, "BOTH": 0.1, "NEITHER": 0.5})   # 改 harness：HARNESS_ONLY / BOTH 降
    strong = arm({"HARNESS_ONLY": 0.5, "MODEL_ONLY": 0.1, "BOTH": 0.1, "NEITHER": 0.5})     # 换模型：MODEL_ONLY / BOTH 降
    got = {r["pattern"]: r["blame"] for r in blame_table(weak_base, weak_mod, strong, delta=0.08)}
    assert got["HARNESS_ONLY"] == "HARNESS" and got["MODEL_ONLY"] == "MODEL" and got["BOTH"] == "MIXED"
    assert got["NEITHER"].startswith("UNKNOWN")
