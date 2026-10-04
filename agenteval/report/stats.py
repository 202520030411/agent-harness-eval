"""配对统计（D-018）：McNemar 精确检验、Benjamini–Hochberg 校正、题级 bootstrap 区间、噪声底。

只用标准库，避免依赖漂移。所有函数都是纯函数。
"""
from __future__ import annotations

import math
import random
from collections import defaultdict


def mcnemar_exact(b: int, c: int) -> float:
    """两配置逐题配对：b = A 过 B 不过 的题数，c = A 不过 B 过 的题数。
    双侧精确 McNemar：在 H0 下 b ~ Binomial(b+c, 0.5)。返回 p 值。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bh_adjust(pvals: list[float]) -> list[float]:
    """Benjamini–Hochberg：返回与输入同序的 q 值。"""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        val = min(prev, pvals[i] * m / rank)
        q[i] = val
        prev = val
    return q


def per_task_rate(records: list[tuple[str, bool]]) -> dict[str, float]:
    """[(task, passed), ...] → 每题通过率（k 次的均值）。"""
    acc: dict[str, list[float]] = defaultdict(list)
    for task, ok in records:
        acc[task].append(1.0 if ok else 0.0)
    return {t: sum(v) / len(v) for t, v in acc.items()}


def paired_compare(a: list[tuple[str, bool]], b: list[tuple[str, bool]], n_boot: int = 10000, seed: int = 0) -> dict:
    """配置 A vs B 的逐题配对比较。
    - delta：B − A 的题级平均通过率之差（百分点）
    - flips：题级 pass@k 意义上的翻转数 b / c（A 过 B 不过 / A 不过 B 过），用于 McNemar
    - ci95：题级 bootstrap（重抽样题目）得到的 delta 区间
    """
    ra, rb = per_task_rate(a), per_task_rate(b)
    tasks = sorted(set(ra) & set(rb))
    if not tasks:
        raise ValueError("no common tasks")
    diffs = [rb[t] - ra[t] for t in tasks]
    delta = sum(diffs) / len(diffs)
    b_flip = sum(1 for t in tasks if ra[t] > 0 and rb[t] == 0)
    c_flip = sum(1 for t in tasks if ra[t] == 0 and rb[t] > 0)
    p = mcnemar_exact(b_flip, c_flip)
    rng = random.Random(seed)
    boots = []
    n = len(tasks)
    for _ in range(n_boot):
        s = [diffs[rng.randrange(n)] for _ in range(n)]
        boots.append(sum(s) / n)
    boots.sort()
    lo, hi = boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]
    return {
        "n_tasks": n, "delta_pp": 100 * delta, "ci95_pp": (100 * lo, 100 * hi),
        "flips_A_pass_B_fail": b_flip, "flips_A_fail_B_pass": c_flip, "mcnemar_p": p,
        "per_task": {t: (ra[t], rb[t]) for t in tasks},
    }


def noise_floor(run1: list[tuple[str, bool]], run2: list[tuple[str, bool]]) -> dict:
    """同一配置两次独立运行：δ = |题级平均通过率之差|（百分点），以及逐题差的分布。"""
    r1, r2 = per_task_rate(run1), per_task_rate(run2)
    tasks = sorted(set(r1) & set(r2))
    diffs = [r2[t] - r1[t] for t in tasks]
    mean1 = sum(r1[t] for t in tasks) / len(tasks)
    mean2 = sum(r2[t] for t in tasks) / len(tasks)
    return {"n_tasks": len(tasks), "mean_run1": mean1, "mean_run2": mean2,
            "delta_pp": 100 * abs(mean2 - mean1),
            "mean_abs_task_diff_pp": 100 * sum(abs(d) for d in diffs) / len(diffs),
            "max_abs_task_diff_pp": 100 * max(abs(d) for d in diffs)}
