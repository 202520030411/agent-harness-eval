# Coding-Agent Failure Attribution and Harness–Model Co-iteration

When a coding agent fails a terminal task, is it the model, the **harness** (the control program around the model: prompts, tool interface, waiting strategy, completion check), or the task itself? This repo is an eight-day solo project that answers that question with controlled experiments on [Terminal-Bench 2.1](https://github.com/harbor-framework/terminal-bench-2-1) via [Harbor](https://github.com/laude-institute/harbor), then feeds the answer back into harness changes and training data.

Two models were studied: **Seed 2.1 lite** (API) and **Qwen3-Coder-30B-A3B** (self-hosted with vLLM on one H200).

> Most design notes are in Chinese. The full write-up is [`docs/PAPER.md`](docs/PAPER.md); every design decision is logged in [`decisions.md`](decisions.md) (D-001 – D-083) and every prediction was pre-registered in [`HYPOTHESES.md`](HYPOTHESES.md) before the run.

## Results

| Question | Finding |
|---|---|
| Can automated LLM judges attribute failures reliably? | Reference labels for 39 failures: 16 decided by the author, 16 checked or revised with model assistance, 2 untagged, 5 adopted where three judges agreed (excluded below to avoid circularity). On the remaining 34, giving judges the hidden tests and reference solution and encoding human-derived decision rules raised strict judge–reference agreement from **44% to 65%** (κ 0.33 → 0.56); the rules were written from part of the same set, so this is partly in-sample. Two judges agreed on **50%** of these failures, with **82%** accuracy on those; disagreements go to human review. A judge re-judging the *same* transcript flips its label 23% of the time, so judge noise must be measured before judge comparisons mean anything. |
| Are the "underspecified task" labels real? | Re-running flagged tasks with only the instruction edited confirmed **7 of 41** Terminal-Bench 2.1 tasks have instruction or test defects (e.g. `extract-elf` 0/6 → 3/3 once an address convention was stated). "Unclear task" splits into interface conventions (fixable by editing the task), domain knowledge, and environment/tool versions (not fixable that way). Filed 3 new issues upstream and added reproduction data to 6 existing threads ([list](docs/tb_issues/POSTED.md)). |
| How much can harness changes fix? (Seed lite) | Nine switches on Terminus 2, ablated with concurrent control arms against a measured noise floor of 8 pp: **none** gave a reproducible pass-rate gain. `adaptive_wait` cut idle turns 27% and input tokens 11% at equal pass rate, and surfaced an unreachable timeout branch upstream ([PR draft](docs/harbor_pr_draft.md)). Prompt-level "verify before finishing" changes cost +29% to +110% and caused timeouts. |
| How much can harness changes fix? (Qwen) | Four harnesses, 30 tasks × 4 runs each: pass rate 16% → 21–22% (not significant). Interface fixes cut turns wasted on malformed output by **93%**. "Claims success while knowing it failed" stays at 23–31% of failures under every harness, so it is model-side. |
| Can training fix the model-side residue? | 111 synthetic Harbor tasks (validated: reference passes, no-op fails, de-duplicated against the benchmark), rejection-sampling fine-tuning with LoRA, then GRPO with real-time hints from a strong model. On tasks the model had never solved, hints from a strong model that watched its progress and stepped in when it went wrong reached a **25%** pass rate during sampling, versus **5–6%** for hints given once before the start. After training, held-out pass rate was unchanged (RL − base **+0.0 pp**, 95% CI [−7.2, +7.2]); hint-assisted successes did not transfer once hints were removed. An apparently significant SFT effect from a first evaluation did not replicate in a concurrent repeat. |

Negative results are reported as they came out; see `docs/LAB_NOTEBOOK.md` for how early readings changed as samples grew.

## Method rules that shaped the results

1. Measure the noise floor first; same-config reruns three hours apart differed by up to 11.5 pp, so all compared arms run **concurrently**.
2. Pre-register predictions and the analysis script before running; report every arm, never pick winners.
3. A subset effect only counts if an **independent batch run after the effect was proposed** reproduces it (one did not, and was retracted: D-050).
4. Judges see full context, are checked for self-consistency, and are calibrated against human labels.
5. The training loss must use the same sampling distribution as the inference server (temperature, top-k/top-p, repetition penalty); a pre-launch multi-agent code review caught this mismatch.

## Layout

| Path | What it is |
|---|---|
| `agenteval/` | Evaluation pipeline: Harbor trial adapter, rule-based failure signals, LLM judges, rubric extraction with partial-order validation, paired bootstrap / McNemar stats, judge agreement, blame table, regression gate (non-zero exit code on regressions) |
| `terminus2_patches/` | Harness switches as a subclass of Harbor's Terminus 2 (`adaptive_wait`, `task_contract`, `verifier_gate`, `deliverable_checkpoint`, `interface_fixes`, `completion_gate`, `teacher_hint`, …). All switches off is byte-identical to upstream (golden test). |
| `train/synth/` | Synthetic task generation and validation, hint generation |
| `train/tb_sft_export.py`, `train/ambig/sft_train.py` | Trajectory filtering / export and LoRA SFT |
| `train/rl/` | GRPO loop: group advantages, hint modes, sampler-matched log-probs, stop rules, resumable state |
| `tools/` | Job launchers and report generators |
| `experiments/` | Harbor job configs and fixed task lists |
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
