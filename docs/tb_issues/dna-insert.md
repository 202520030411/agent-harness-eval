# [terminal-bench] dna-insert: insertion boundary is ambiguous and the grader's oligotm version differs from what a solver can install

**Task:** `dna-insert` (terminal-bench 2.1)

**Problem 1 — ambiguous insertion boundary.** The insert's flanks repeat (`...gag|tagatta...cagaaag|caag...`), so the same output plasmid can be described with the insert shifted by 2 bp. `tests/test_outputs.py` hard-codes the left-aligned insert string and recomputes the annealing regions by locating it inside `rc(rev) + fwd`. A solver who uses the right-aligned boundary (what longest-common-prefix gives) designs a valid primer pair whose annealing regions are re-split by the grader, and the recomputed Tm difference exceeds 5 °C (observed 7.8 °C and 5.4 °C for pairs the solver measured at 1.6 °C / 0.003 °C). The instruction says nothing about alignment.

**Problem 2 — tool version.** `oligotm` is not installed in the task image; solvers `apt-get install primer3`. In one run the solver's oligotm gave 58.04 °C for its reverse annealing region and the grader's gave 55.86 °C for the same sequence, flipping the verdict.

**Evidence.** Baseline 1/6 passes. Rewriting the instruction to state the left-aligned boundary rule and to install primer3 the same way the grader does → 3/3 passes with the same model.

**Suggested fix.** State the boundary convention (or accept any equivalent alignment by checking the constraints under every valid split), and preinstall oligotm in the image (or pin the version in `tests/test.sh` and the instruction).
