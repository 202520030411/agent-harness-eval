"""标注一致率：两份主标签（判官 vs 判官、判官 vs 人工）的原始一致率与 Cohen's κ；同时给 TB 三大类折叠后的 κ。"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from agenteval.judge.attribution import LABELS, parse

TB_CLASS = {k: v[0] for k, v in LABELS.items()}


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def load_primary(path: Path) -> dict[str, dict]:
    """judge.jsonl 或人工标注 csv → {trial_id: {primary, onset}}。"""
    out = {}
    if path.suffix == ".csv":
        with path.open() as f:
            for r in csv.DictReader(f):
                p = (r.get("human_primary") or "").strip().upper()
                if p:
                    o = (r.get("human_onset") or "").strip()
                    sec = [x.strip().upper() for x in (r.get("human_secondary") or "").split(",") if x.strip()]
                    out[r["trial_id"]] = {"primary": p, "onset": int(o) if o.isdigit() else None, "secondary": sec}
    else:
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                pr = parse(r.get("judge_raw") or "")
                out[r["trial_id"]] = {"primary": r["judge_primary"], "onset": r.get("judge_onset"), "secondary": (pr or {}).get("secondary", [])}
    return out


def agreement(x: dict[str, dict], y: dict[str, dict], name_x: str, name_y: str) -> dict:
    ids = sorted(set(x) & set(y))
    a = [x[i]["primary"] for i in ids]; b = [y[i]["primary"] for i in ids]
    a_cls = [TB_CLASS.get(v, "NONE") for v in a]; b_cls = [TB_CLASS.get(v, "NONE") for v in b]
    onset_pairs = [(x[i]["onset"], y[i]["onset"]) for i in ids if x[i].get("onset") is not None and y[i].get("onset") is not None]
    onset_within2 = sum(1 for p, q in onset_pairs if abs(p - q) <= 2) / len(onset_pairs) if onset_pairs else None
    conf = Counter(zip(a, b))
    # 宽松口径：一方的主标签落在另一方的 {主, 次} 里就算一致（失败是因果链，两家可能各指一环）
    def lenient(i):
        sx = {x[i]["primary"], *x[i].get("secondary", [])}; sy = {y[i]["primary"], *y[i].get("secondary", [])}
        return x[i]["primary"] in sy or y[i]["primary"] in sx
    lenient_rate = sum(1 for i in ids if lenient(i)) / len(ids) if ids else None
    return {"x": name_x, "y": name_y, "n": len(ids),
            "raw_agreement": sum(1 for p, q in zip(a, b) if p == q) / len(ids) if ids else None,
            "kappa_primary": cohen_kappa(a, b), "kappa_tb_class": cohen_kappa(a_cls, b_cls),
            "raw_agreement_tb_class": sum(1 for p, q in zip(a_cls, b_cls) if p == q) / len(ids) if ids else None,
            "lenient_agreement": lenient_rate,
            "onset_pairs": len(onset_pairs), "onset_within_2_steps": onset_within2,
            "disagreements": [{"trial_id": i, name_x: x[i]["primary"], name_y: y[i]["primary"], "lenient": lenient(i)} for i in ids if x[i]["primary"] != y[i]["primary"]],
            "confusion_top": [{"pair": f"{p} vs {q}", "n": n} for (p, q), n in conf.most_common(12)]}


def render(r: dict) -> str:
    L = [f"# 一致率：{r['x']} vs {r['y']}（n={r['n']}）", "",
         f"- 主标签：原始一致 {100*(r['raw_agreement'] or 0):.1f}%，Cohen's κ = {r['kappa_primary'] and round(r['kappa_primary'], 3)}",
         f"- 折叠到 TB 三大类：原始一致 {100*(r['raw_agreement_tb_class'] or 0):.1f}%，κ = {r['kappa_tb_class'] and round(r['kappa_tb_class'], 3)}",
         f"- 宽松口径（主标签落在对方的主/次标签里）：{100*(r['lenient_agreement'] or 0):.1f}%",
         f"- onset 相差 ≤2 轮的比例：{r['onset_within_2_steps'] and round(100*r['onset_within_2_steps'])}%（{r['onset_pairs']} 对）", "",
         "## 分歧", ""]
    for d in r["disagreements"]:
        L.append(f"- {d['trial_id']}: {d[r['x']]} / {d[r['y']]}{'（宽松口径下一致）' if d.get('lenient') else ''}")
    return "\n".join(L) + "\n"
