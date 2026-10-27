# Coding-Agent Failure Attribution and Harness–Model Co-iteration

**English** | [中文](README.zh.md)

When a coding agent fails a terminal task, is it the model, the **harness** (the control program around the model: prompts, tool interface, waiting strategy, completion check), or the task itself? This repo is a solo project (September–October 2026) that answers that question with controlled experiments on [Terminal-Bench 2.1](https://github.com/harbor-framework/terminal-bench-2-1) via [Harbor](https://github.com/laude-institute/harbor), feeds the answer back into harness changes and training data, and finally wraps the harness side into a self-improving loop with a calibrated statistical gate.

Two models were studied: **Seed 2.1 lite** (API) and **Qwen3-Coder-30B-A3B** (self-hosted with vLLM on one H200).

> Most design notes are in Chinese. The full write-up is [`docs/PAPER.md`](docs/PAPER.md); every design decision is logged in [`decisions.md`](decisions.md) (D-001 – D-097) and every prediction was pre-registered in [`HYPOTHESES.md`](HYPOTHESES.md) before the run.

## Results

| Question | Finding |
|---|---|
| Can automated LLM judges attribute failures reliably? | Reference labels for 39 failures: 16 decided by the author, 16 checked or revised with model assistance, 2 untagged, 5 adopted where three judges agreed (excluded below to avoid circularity). On the remaining 34, giving judges the hidden tests and reference solution and encoding human-derived decision rules raised strict judge–reference agreement from **44% to 65%** (κ 0.33 → 0.56); the rules were written from part of the same set, so this is partly in-sample. Two judges agreed on **50%** of these failures, with **82%** accuracy on those; disagreements go to human review. A judge re-judging the *same* transcript flips its label 23% of the time, so judge noise must be measured before judge comparisons mean anything. |
| Are the "underspecified task" labels real? | Re-running flagged tasks with only the instruction edited confirmed **7 of 41** Terminal-Bench 2.1 tasks have instruction or test defects (e.g. `extract-elf` 0/6 → 3/3 once an address convention was stated). "Unclear task" splits into interface conventions (fixable by editing the task), domain knowledge, and environment/tool versions (not fixable that way). Filed 3 new issues upstream and added reproduction data to 6 existing threads ([list](docs/tb_issues/POSTED.md)). |
| How much can harness changes fix? (Seed lite) | Nine switches on Terminus 2, ablated with concurrent control arms against a measured noise floor of 8 pp: **none** gave a reproducible pass-rate gain. `adaptive_wait` cut idle turns 27% and input tokens 11% at equal pass rate, and surfaced an unreachable timeout branch upstream ([PR draft](docs/harbor_pr_draft.md)). Prompt-level "verify before finishing" changes cost +29% to +110% and caused timeouts. |
| How much can harness changes fix? (Qwen) | Four harnesses, 30 tasks × 4 runs each: pass rate 16% → 21–22% (not significant). Interface fixes cut turns wasted on malformed output by **93%**. "Claims success while knowing it failed" stays at 23–31% of failures under every harness, so it is model-side. |
| Can a self-improving loop find and validate harness changes? (Qwen) | A loop that mines failure patterns, has LLMs propose harness changes with pre-registered predictions, and keeps a change only if it passes a calibrated gate on concurrent, task-paired A/B runs. One change passed: a reminder that costs no model turn and fires when Qwen keeps writing a file **one line per turn** with `echo >>` (26% of development-set attempts; about 1 in 230 such attempts passed). The habit fell **92–95%**; total turns fell **21–30%** and input tokens **24–31%** on the development set and on 37 held-out tasks; pass rate showed **no reliable change** (+1.6, +3.4, −1.8 pp, all CIs include 0). Details below. |
| Can training fix the model-side residue? | 111 synthetic Harbor tasks (validated: reference passes, no-op fails, de-duplicated against the benchmark), rejection-sampling fine-tuning with LoRA, then GRPO with real-time hints from a strong model. On tasks the model had never solved, hints from a strong model that watched its progress and stepped in when it went wrong reached a **25%** pass rate during sampling, versus **5–6%** for hints given once before the start. After training, held-out pass rate was unchanged (RL − base **+0.0 pp**, 95% CI [−7.2, +7.2]); hint-assisted successes did not transfer once hints were removed. An apparently significant SFT effect from a first evaluation did not replicate in a concurrent repeat. |

Negative results are reported as they came out; see `docs/LAB_NOTEBOOK.md` for how early readings changed as samples grew.

## Self-improving harness loop (D-084 – D-097)

The loop is in `agenteval/loop/` and driven by `tools/loop_cycle.py`; the full account (in Chinese) is [`experiments/loop/README.md`](experiments/loop/README.md) and decisions D-084 – D-097.

```
observe trajectories ──▶ find failure patterns ──▶ LLMs propose a change + pre-registered prediction
        ▲                                                         │
        └── promote / reject ◀── statistical gate ◀── concurrent A/B on 74 dev tasks × 4
```

**Grading first.** Synthetic tasks were originally graded inside the agent's own container. A scripted red-team agent (`tools/drill_agent.py`, 8 attack types, no model) fooled the old grader **16 of 24** times; after moving grading into a separate container that receives only `/app`, replaying the task build, and planting a decoy answer file, it fooled it **0 of 24** times. Across the 2,184 trials of this case, nothing touched the decoy and no trial was flagged as suspect.

**The gate** (`agenteval/loop/accept.py`). Task-paired bootstrap intervals. A change is accepted either as a quality gain (CI above 0 and ≥ 8 pp) or as an efficiency gain (turns, input tokens or minutes ≥ 10% lower at alpha/3, with the pass-rate CI lower bound no worse than −min(8 pp, 25% of the baseline pass rate)). Guards reject rising cheating flags or always-solved tasks dropping to zero, and close the efficiency path if the share of submissions that fail rises. Calibrated on random half-splits of identical configurations: false accept **2.5–6%**, false reject **5.5–9%**. Arms that did not run concurrently, lost tasks, or > 5% infrastructure errors make the comparison invalid instead of being skipped.

**What happened to the one change that passed** (`append_nudge`, `terminus2_patches/agent.py`):
- Round 1 was blocked by my own guard, which then compared "submitted and failed" to all trials. Trials that used to hit the 100-turn cap (43 → 1) now reached submission and mostly still failed, which looked like giving up early, although the share of submissions that failed was unchanged (78.2% vs 78.5%). I did not re-judge that round: the guard was redefined, recalibrated (error rates unchanged), and the change was retested once on fresh runs through a one-time retest path the code enforces. It passed (turns −21%, input tokens −24%, pass +3.4 pp [−0.3, +7.4]); the old guard rose again on the new data while the corrected one did not.
- The replication batch was invalid (the GPU machine ran out of credit mid-run, 14% / 10% infrastructure errors), so by the loop's own rules the change was **not promoted**.
- On 37 held-out tasks: habit −95%, turns −30%, input tokens −31%, pass −1.8 pp [−8.1, +3.6]. Wall-clock time per task did not drop: output tokens per attempt stayed about the same while each turn got longer, so the saving is in turns and input tokens.
- On 30 Terminal-Bench tasks the pass rate rose 10 pp, but the reminder fired in only 3 of them and 8 of the 9 extra passes came from tasks where it never fired — the two arms saw identical prompts there, so this is noise, not an effect.

**Where the pattern came from.** The loop's first observation step only counted failure types from fixed rules, and this habit was not one of them; it was found while building the loop by analyzing trajectory statistics, then added as a rule. A later automated discovery step (two LLM judges reading 80 failed trajectories, with this pattern deliberately left off their list) rediscovered it with **56% recall**.

**The proposer rewriting its own prompt.** The proposer's prompt is split into a rewritable playbook ([`P0`](experiments/loop/playbooks/P0.md) → [`P1`](experiments/loop/playbooks/P1.md)) and a fixed output format; scope limits, the text screen for task leakage, and human approval of any text shown to the agent are enforced in code. Given its past predictions and outcomes, the proposer added "estimate how often the target behavior occurs and the most it could save before proposing" — its earlier three proposals had been withdrawn for exactly that reason. In the next round neither P0 nor P1 produced a change worth testing, and Qwen acting as its own proposer produced a duplicate and a reworded near-duplicate with a mis-targeted prediction. A "bounce the submission if the agent's own last check failed" gate was simulated offline (90–100% precision) but could affect at most ~10% of attempts, too little to test at this sample size, so it was not run.

## Method rules that shaped the results

1. Measure the noise floor first; same-config reruns three hours apart differed by up to 11.5 pp, so all compared arms run **concurrently**.
2. Pre-register predictions and the analysis script before running; report every arm, never pick winners.
3. A subset effect only counts if an **independent batch run after the effect was proposed** reproduces it (one did not, and was retracted: D-050).
4. Judges see full context, are checked for self-consistency, and are calibrated against human labels.
5. The training loss must use the same sampling distribution as the inference server (temperature, top-k/top-p, repetition penalty); a pre-launch multi-agent code review caught this mismatch.
6. Harden the grader before trusting any improvement: red-team it with scripted cheating first.
7. When a rule turns out to be wrong after seeing data, fix the rule and retest on fresh runs; never re-judge the data that exposed it.

## Layout

| Path | What it is |
|---|---|
| `agenteval/` | Evaluation pipeline: Harbor trial adapter, rule-based failure signals, LLM judges, rubric extraction with partial-order validation, paired bootstrap / McNemar stats, judge agreement, blame table, regression gate (non-zero exit code on regressions) |
| `agenteval/loop/` | Self-improving loop: failure modes, reflection, proposer prompts and playbook rewriting, failure discovery, text screen, scope of changeable options, version registry, acceptance gate |
| `terminus2_patches/` | Harness switches as a subclass of Harbor's Terminus 2 (`adaptive_wait`, `task_contract`, `verifier_gate`, `deliverable_checkpoint`, `interface_fixes`, `completion_gate`, `teacher_hint`, …). All switches off is byte-identical to upstream (golden test). |
| `train/synth/` | Synthetic task generation and validation, hint generation, grader hardening (`harden.py`) |
| `train/tb_sft_export.py`, `train/ambig/sft_train.py` | Trajectory filtering / export and LoRA SFT |
| `train/rl/` | GRPO loop: group advantages, hint modes, sampler-matched log-probs, stop rules, resumable state |
| `tools/` | Job launchers and report generators; `loop_cycle.py` (loop CLI), `chain_round.py` (server-side chaining), `drill_agent.py` / `run_drills.py` (grader red-team), `final_report.py` |
| `experiments/` | Harbor job configs and fixed task lists; `experiments/loop/` holds the loop's registry, pre-registrations and playbooks |
| `reports/` | Aggregate results only (summaries, comparisons, figures) |
| `docs/` | Design, failure taxonomy, task audit, lab notebook, paper-style write-up |

## Running

```bash
pip install -e . pytest
python -m pytest -q tests      # tests needing torch/transformers/peft or harbor are skipped if those are missing
```

Running experiments needs Harbor 0.23, Docker, and either a model API key (read from the host environment, never passed into task containers) or a vLLM server. Scripts that talk to the GPU machine read `POD_HOST` / `POD_PORT` from the environment.

## Data policy

Terminal-Bench task files carry a canary string and must not end up in training corpora. This repo therefore does **not** include task instructions, hidden tests, rewritten instructions, raw trajectories, judge outputs that quote tests, or the human labeling sheets. Only task names and aggregate numbers appear here.
