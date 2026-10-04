from agenteval.report.stats import bh_adjust, mcnemar_exact, noise_floor, paired_compare


def test_mcnemar_known_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert abs(mcnemar_exact(5, 5) - 1.0) < 1e-9
    # b=0, c=6 → 双侧 p = 2 * (1/2^6) = 0.03125
    assert abs(mcnemar_exact(0, 6) - 0.03125) < 1e-9
    assert mcnemar_exact(1, 9) < 0.05 < mcnemar_exact(2, 6)


def test_bh_monotone_and_bounded():
    q = bh_adjust([0.01, 0.04, 0.03, 0.20])
    assert all(0 <= x <= 1 for x in q)
    assert q[0] <= q[2] <= q[1] <= q[3]
    assert abs(q[3] - 0.20) < 1e-9


def test_paired_compare_and_noise_floor():
    a = [("t1", True), ("t1", False), ("t2", False), ("t2", False), ("t3", True), ("t3", True)]
    b = [("t1", True), ("t1", True), ("t2", True), ("t2", False), ("t3", True), ("t3", True)]
    r = paired_compare(a, b, n_boot=2000, seed=1)
    assert r["n_tasks"] == 3 and r["flips_A_fail_B_pass"] == 1 and r["flips_A_pass_B_fail"] == 0
    assert r["delta_pp"] > 0 and r["ci95_pp"][0] <= r["delta_pp"] <= r["ci95_pp"][1]
    nf = noise_floor(a, a)
    assert nf["delta_pp"] == 0.0 and nf["max_abs_task_diff_pp"] == 0.0
