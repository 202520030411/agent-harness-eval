"""统一记录：session = 题，trace = trial，observation = 轮；标签按 Score 形状（D-019）。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

Source = Literal["RULE", "JUDGE", "HUMAN"]
Blame = Literal["MODEL", "HARNESS", "MIXED", "ENVIRONMENT", "TASK", "UNKNOWN"]
TBClass = Literal["Execution", "Coherence", "Verification", "ENVIRONMENT", "TASK", "NONE"]


@dataclass
class Step:
    step_id: int
    source: str                      # user | agent | system
    message: str = ""
    keystrokes: list[str] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)
    claimed_complete: bool = False
    observation_text: str = ""
    truncated: bool = False
    parse_error: bool = False
    compaction_boundary: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost: float = 0.0
    has_reasoning: bool = False      # 只记有无，内容永远不进判官视图


@dataclass
class FailureLabel:
    name: str
    value: Any                       # bool / 类别名 / 数值
    data_type: str                   # BOOLEAN | CATEGORICAL | NUMERIC | TEXT
    source: Source
    tb_class: TBClass
    blame_candidate: Blame
    confidence: float
    comment: str                     # 证据原文 + step_id
    onset_step: int | None = None
    config_id: str | None = None
    kind: str = "failure"           # failure | count（计数型，通过与失败都有）


@dataclass
class TrialRecord:
    trial_id: str
    task_name: str
    config_id: str
    attempt: int
    job_name: str
    agent_name: str
    model_name: str
    reward: float | None             # None = 没拿到明确判分
    status: str                      # ok | setup_failed | agent_error | verifier_error | agent_timeout
    exception_type: str | None
    exception_message: str | None
    n_episodes: int
    summarization_count: int
    wall_clock_sec: float | None
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    cost: float
    steps: list[Step]
    labels: list[FailureLabel] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.reward is not None and self.reward >= 1.0

    @property
    def agent_steps(self) -> list[Step]:
        return [s for s in self.steps if s.source == "agent"]

    def to_dict(self, with_steps: bool = False) -> dict[str, Any]:
        d = asdict(self)
        if not with_steps:
            d["steps"] = len(self.steps)
        return d
