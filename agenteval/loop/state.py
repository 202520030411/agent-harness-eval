"""harness 的版本记录：每个候选都是一个版本，有父版本、改动、预注册、证据和状态；只追加、不覆盖。

状态流转：
  init_root ──▶ promoted（根版本，直接成为 current）
  proposed ──主评测──▶ evaluated；主评测 REJECT ──▶ rejected；主评测 INVALID ──▶ 状态不变，可以换新 job 重跑
  evaluated（主评测 ACCEPT_* 或 PROVISIONAL）──复现──▶ 复现 ACCEPT_* 才能上线；复现是别的结果（INVALID 除外）──▶ rejected
  evaluated（主评测 INCONCLUSIVE）──判分规则改过之后重测（retest，D-088）──▶ 重测结果代替主评测，之后照常要复现
  promoted ──出问题──▶ rolled_back（current 退回父版本）
  proposed / evaluated ──人或效果上限检查撤下──▶ withdrawn
current 永远指向最后一个 promoted 且没被回滚的版本。文件格式是 JSON，人能直接读。

防自欺（D-085，2026-10-12 按代码检查的结果补上）：
- 主评测、复现各只算一次；只有 INVALID（数据有问题）可以重跑，而且必须用新跑的 job。
- 复现的两个臂都必须是新跑的 job，不能拿主评测的数据再评一遍。没有"跳过复现"的选项。
- 重测（D-088）：只给主评测是 INCONCLUSIVE 的版本；判分代码的指纹必须和主评测时不同（规则真的改了）；必须写明是哪条决定
  改的规则（decision_ref）；每个版本只能一次；两臂都是新跑的 job。不能用来"换个规则把同一批数据再判一次"。
- 文件带整体指纹（state_hash）：在程序之外手改过文件，下次读取直接报错。
- 改写时加文件锁（Registry.edit），两个命令同时改不会互相覆盖。
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from agenteval.loop.scope import TEXT, effective_options, fingerprint, policy_options, validate_change

TERMINAL = {"promoted", "rejected", "rolled_back", "withdrawn"}
ACCEPTS = ("ACCEPT_QUALITY", "ACCEPT_EFFICIENCY")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass
class Version:
    version: str
    parent: str | None
    agent: str
    options: dict[str, Any]
    fingerprint: str
    status: str                                   # proposed | evaluated | promoted | rejected | rolled_back | withdrawn
    created_at: str
    change: dict[str, Any] = field(default_factory=dict)        # 相对父版本的有效改动
    rationale: str = ""
    prereg: dict[str, Any] = field(default_factory=dict)        # 目标毛病、机制指标与预测、通过率预测、证伪条件
    source: str = ""                                             # 谁提的：human / proposer:<model>
    evaluations: list[dict[str, Any]] = field(default_factory=list)   # 每次评测的决定与关键数字（附 job 名）
    notes: list[str] = field(default_factory=list)
    model: str = ""                                              # 这个版本是针对哪个被测模型的（指纹不含模型）
    text_approval: dict[str, Any] = field(default_factory=dict)  # 文字类改动（提醒、skill）谁、什么时候批准的（D-089）


@dataclass
class Registry:
    versions: dict[str, Version] = field(default_factory=dict)
    current: str | None = None
    log: list[dict[str, Any]] = field(default_factory=list)

    # ---------- 读写 ----------
    @classmethod
    def load(cls, path: Path) -> "Registry":
        path = Path(path)
        if not path.exists():
            return cls()
        d = json.loads(path.read_text())
        body = {"current": d.get("current"), "versions": d.get("versions", {}), "log": d.get("log", [])}
        if "state_hash" in d and d["state_hash"] != _digest(body):
            raise ValueError(f"{path} was changed outside the Registry code (state hash mismatch); refusing to use it")
        return cls(versions={k: Version(**v) for k, v in body["versions"].items()}, current=body["current"], log=body["log"])

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"current": self.current, "versions": {k: asdict(v) for k, v in self.versions.items()}, "log": self.log}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**body, "state_hash": _digest(body)}, ensure_ascii=False, indent=1))
        tmp.replace(path)

    @classmethod
    @contextlib.contextmanager
    def edit(cls, path: Path) -> Iterator["Registry"]:
        """加锁读出、修改、写回：同一时间只有一个命令能改版本记录。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path.with_suffix(".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            reg = cls.load(path)
            yield reg
            reg.save(path)

    def _event(self, kind: str, version: str, **kw) -> None:
        self.log.append({"at": _now(), "event": kind, "version": version, **kw})

    # ---------- 版本 ----------
    def init_root(self, version: str, agent: str, options: dict[str, Any], rationale: str, source: str = "human",
                  model: str = "") -> Version:
        """第一个版本（当前在用的 harness）直接作为 promoted 的根。"""
        if self.versions:
            raise ValueError("registry already initialised")
        v = Version(version=version, parent=None, agent=agent, options=policy_options(options), fingerprint=fingerprint(options),
                    status="promoted", created_at=_now(), rationale=rationale, source=source, model=model)
        self.versions[version] = v
        self.current = version
        self._event("init", version, model=model)
        return v

    def find_by_fingerprint(self, fp: str, model: str | None = None) -> list[Version]:
        return [v for v in self.versions.values() if v.fingerprint == fp and (model is None or v.model == model)]

    def propose(self, parent: str, changes: dict[str, Any], *, rationale: str, prereg: dict[str, Any], source: str,
                version: str | None = None, model: str | None = None) -> tuple[Version | None, list[str]]:
        """在父版本上加一个候选；改动越界、或与已有版本（同一个被测模型）是同一个 harness 时拒绝并给出原因。"""
        if parent not in self.versions:
            return None, [f"unknown parent {parent}"]
        if version is not None and version in self.versions:
            return None, [f"version id {version} already exists"]
        base = self.versions[parent]
        model = base.model if model is None else model
        val = validate_change(base.options, changes)
        if not val.ok:
            return None, val.errors
        fp = fingerprint(val.options)
        dup = self.find_by_fingerprint(fp, model)
        if dup:
            return None, [f"duplicate of existing version {dup[0].version} (status {dup[0].status})"]
        missing = [k for k in ("target_mode", "mechanism_metric", "predicted_mechanism_change", "predicted_pass_change", "falsified_if")
                   if prereg.get(k) is None or str(prereg.get(k)).strip() == ""]
        if missing:
            return None, [f"pre-registration incomplete: missing {missing}"]
        vid = version or self._next_id(parent)
        v = Version(version=vid, parent=parent, agent=base.agent, options=val.options, fingerprint=fp, status="proposed",
                    created_at=_now(), change=val.effective_changes, rationale=rationale, prereg=prereg, source=source, model=model)
        self.versions[vid] = v
        self._event("propose", vid, parent=parent, change=val.effective_changes, source=source)
        return v, []

    def needs_text_approval(self, version: str) -> bool:
        """改动里有文字（text 档：提醒、skill），而且还没人批准过（D-089）。"""
        v = self.versions[version]
        return any(k in TEXT for k in v.change) and not v.text_approval

    def approve_text(self, version: str, *, by: str, note: str = "") -> None:
        """人看过这个候选的全部文字之后调用；记下是谁、什么时候、文字的指纹（之后文字变了就对不上）。"""
        v = self.versions[version]
        if not any(k in TEXT for k in v.change):
            raise ValueError(f"{version} has no text changes to approve")
        if v.status != "proposed":
            raise ValueError(f"{version} is {v.status}; text can only be approved before evaluation")
        if not by.strip():
            raise ValueError("approve_text needs the name of the person who approved it")
        blob = json.dumps({k: v.change[k] for k in TEXT if k in v.change}, sort_keys=True, ensure_ascii=False)
        v.text_approval = {"by": by, "at": _now(), "note": note, "text_hash": hashlib.sha256(blob.encode()).hexdigest()[:12]}
        self._event("approve_text", version, by=by)

    def _next_id(self, parent: str) -> str:
        n = 1 + sum(1 for v in self.versions.values() if v.parent == parent)
        stem = parent.split("+")[0]
        vid = f"{stem}+c{n:02d}"
        while vid in self.versions:
            n += 1
            vid = f"{stem}+c{n:02d}"
        return vid

    @staticmethod
    def _counted(v: Version, purpose: str) -> list[dict[str, Any]]:
        return [e for e in v.evaluations if e["purpose"] == purpose and e["decision"] != "INVALID"]

    def _first(self, v: Version) -> dict[str, Any] | None:
        """决定能否复现、能否上线的那次判定：有重测就用重测（D-088），否则用主评测。"""
        rets, prims = self._counted(v, "retest"), self._counted(v, "primary")
        return (rets or prims or [None])[0]

    def record_evaluation(self, version: str, decision: dict[str, Any], *, baseline_job: str, candidate_job: str,
                          purpose: str = "primary", extra: dict[str, Any] | None = None) -> None:
        """记一次评测结果（primary = 第一次评测；replication = 独立批次复现）。规则见文件头。"""
        v = self.versions[version]
        if v.status in TERMINAL:
            raise ValueError(f"{version} is {v.status}; evaluations are closed")
        if purpose not in ("primary", "replication", "retest"):
            raise ValueError(f"unknown purpose {purpose!r}")
        used = {j for e in v.evaluations for j in (e["baseline_job"], e["candidate_job"])}
        if baseline_job in used or candidate_job in used or baseline_job == candidate_job:
            raise ValueError(f"{version}: every evaluation must use newly run jobs for both arms "
                             f"(already used: {sorted(used)})")
        prims, reps, rets = self._counted(v, "primary"), self._counted(v, "replication"), self._counted(v, "retest")
        if purpose == "primary" and prims:
            raise ValueError(f"{version} already has a primary evaluation ({prims[0]['decision']}); only INVALID results may be re-run")
        if purpose == "retest":
            if not prims or prims[0]["decision"] != "INCONCLUSIVE":
                raise ValueError(f"{version}: a retest needs an INCONCLUSIVE primary evaluation")
            if rets:
                raise ValueError(f"{version} was already retested once ({rets[0]['decision']})")
            if not (extra or {}).get("decision_ref"):
                raise ValueError(f"{version}: a retest must name the decision record that changed the gate (decision_ref)")
            if (extra or {}).get("gate_code") in (None, prims[0].get("gate_code")):
                raise ValueError(f"{version}: a retest is only allowed after the gate code changed")
        if purpose == "replication":
            first = self._first(v)
            if not first or first["decision"] not in (*ACCEPTS, "PROVISIONAL"):
                raise ValueError(f"{version}: replication needs an accepted or provisional primary evaluation")
            if reps:
                raise ValueError(f"{version} was already replicated once ({reps[0]['decision']})")
        dec = decision.get("decision")
        v.evaluations.append({"at": _now(), "purpose": purpose, "baseline_job": baseline_job, "candidate_job": candidate_job,
                              "decision": dec, "reasons": decision.get("reasons", []), "pass": decision.get("pass"),
                              "efficiency": decision.get("efficiency"), "guards": decision.get("guards"),
                              "mechanism": decision.get("mechanism"), **(extra or {})})
        if dec == "INVALID":
            pass                                                    # 数据有问题：状态不变，换新 job 重跑
        elif purpose in ("primary", "retest") and dec == "REJECT":
            v.status = "rejected"
            v.notes.append(f"{purpose} evaluation REJECT: {decision.get('reasons')}")
        elif purpose == "replication" and dec not in ACCEPTS:
            v.status = "rejected"
            v.notes.append(f"replication was {dec}: {decision.get('reasons')}")
        else:
            v.status = "evaluated"
        self._event("evaluate", version, decision=dec, purpose=purpose, baseline_job=baseline_job, candidate_job=candidate_job)

    def promotable(self, version: str) -> tuple[bool, str]:
        v = self.versions[version]
        if v.status != "evaluated":
            return False, f"status is {v.status}"
        if v.parent != self.current:
            return False, f"parent {v.parent} is not the current version {self.current}; re-evaluate against current"
        first, reps = self._first(v), self._counted(v, "replication")
        if not first:
            return False, "no primary evaluation"
        if first["decision"] not in (*ACCEPTS, "PROVISIONAL"):
            return False, f"{first['purpose']} decision was {first['decision']}"
        if not reps:
            return False, "needs an independent replication batch (D-050 rule)"
        if reps[0]["decision"] not in ACCEPTS:
            return False, f"replication decision was {reps[0]['decision']}"
        return True, "ok"

    def promote(self, version: str) -> None:
        ok, why = self.promotable(version)
        if not ok:
            raise ValueError(f"cannot promote {version}: {why}")
        self.versions[version].status = "promoted"
        prev = self.current
        self.current = version
        self._event("promote", version, previous=prev)

    def reject(self, version: str, reason: str) -> None:
        v = self.versions[version]
        if v.status not in ("proposed", "evaluated"):
            raise ValueError(f"{version} is {v.status}; only proposed or evaluated candidates can be rejected")
        v.status = "rejected"
        v.notes.append(reason)
        self._event("reject", version, reason=reason)

    def withdraw(self, version: str, reason: str) -> None:
        """不再评测就撤下一个候选（例如：用已有日志算出的效果上限达不到接受门的门槛，花钱评测也不可能通过）。"""
        v = self.versions[version]
        if v.status not in ("proposed", "evaluated"):
            raise ValueError(f"{version} is {v.status}; only proposed or evaluated candidates can be withdrawn")
        v.status = "withdrawn"
        v.notes.append(reason)
        self._event("withdraw", version, reason=reason)

    def rollback(self, reason: str) -> str:
        """当前版本出了问题：标记 rolled_back，current 退回到它的父版本。返回新的 current。"""
        cur = self.versions.get(self.current or "")
        if cur is None or cur.parent is None:
            raise ValueError("nothing to roll back (current is the root)")
        cur.status = "rolled_back"
        cur.notes.append(reason)
        self.current = cur.parent
        self._event("rollback", cur.version, reason=reason, now_current=self.current)
        return self.current

    def lineage(self, version: str | None = None) -> list[str]:
        out, v = [], version or self.current
        while v:
            out.append(v)
            v = self.versions[v].parent
        return out[::-1]

    def current_options(self) -> dict[str, Any]:
        return effective_options(self.versions[self.current].options) if self.current else {}
