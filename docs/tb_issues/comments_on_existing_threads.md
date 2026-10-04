# Comments to post on existing terminal-bench-2-1 threads

Each block is one comment. All evidence is from our own runs (Seed 2.1 lite through Terminus 2 on Harbor 0.23, unless stated); trial counts are trials, not tasks. Our task-rewrite experiments changed only `instruction.md` (and, where stated, the image), never tests or reference solutions.

---

## Comment on issue #194 (extract-elf: PIE address requirements missing)

Independent replication, from the solver side. With a weaker model (Seed 2.1 lite, Terminus 2) the unchanged task failed **6/6** with `Only found 0.00% of expected values`; every trajectory hard-coded `BASE = 0x400000` after reading the example output, exactly the failure mode you describe. Adding the contract you propose to `instruction.md` (4-byte little-endian words from `.text/.data/.rodata`, key = `sh_addr + offset` in decimal, no load bias; and a note that the script is also run on a freshly gcc-compiled binary) — with tests and `a.out` untouched — the same model passed **3/3**. So the example address alone is enough to send solvers down the wrong path, and the one-paragraph fix is sufficient.

---

## Comment on issue #100 (dna-insert: three possible insertion sites)

Same finding from a different angle, plus a second, independent defect on this task. Baseline: 1/6 with Seed 2.1 lite. Rewriting the instruction to state the left-aligned insertion boundary (the one `test_outputs.py` hard-codes) fixed the boundary problem but still gave **0/3** — because `oligotm` is not in the image, solvers `apt-get install primer3`, and that build reports different Tm values from the grader's (58.04 °C vs 55.86 °C for the same reverse annealing region in one run), which flips the ≤5 °C verdict. With the boundary stated **and** the same oligotm build the grader uses, the model passed **3/3**. Suggest the fix covers both: either accept any equivalent alignment (check the constraints under every valid split) or state the convention; and preinstall/pin `oligotm` in the image.

---

## Comment on issue #133 (configure-git-webserver: soft verifier passes without working SSH)

The same sentence causes false negatives as well as the false positive you found. `instruction.md` ends with *"I'll setup login with the server to work, you don't have to worry about that."* `verify.sh` then needs a local `user` account with ssh access (it installs a key into `/home/user/.ssh` and runs `git clone user@localhost:/git/server`). In our runs the solver ran `id user` → "no such user", quoted that sentence, and deliberately did not create the account; the clone failed, no push happened, and the curl check returned 404 (`fatal: not a git repository` in verifier stderr) although the solver's own end-to-end test as another local user had passed. Since PR #37 tightens the verifier, it would help to also fix the instruction in the same change ("the grader will connect as local user `user` over ssh; make sure that works"), or have `verify.sh` create the account before installing the key.

---

## Comment on PR #1 (raman-fitting: specify cm⁻¹ conversion and Lorentzian conventions)

Data in support. Unchanged task: **0/6** (Seed 2.1 lite) and the strong-model control also failed (0/1, gpt-6-sol). Adding only the `x_cm = 1e7 / x_raw` conversion to the instruction made the peak positions come out right (~1580 / ~2670 cm⁻¹) but the trials still failed **0/3** on the remaining hidden conventions — the HWHM-vs-FWHM and height-vs-area choices this PR spells out, plus the fitting range around each peak. So the conversion sentence alone is not enough; all three sentences in this PR are load-bearing, and stating the fitting window would remove the last hidden choice.

---

## Comment on PR #6 (pytorch-model-cli: specify image preprocessing)

One more data point. In 28 trials with Seed 2.1 lite (several harness configurations), 26 used plain `/255` scaling and 25 of those passed; the one `/255` failure was a genuine solver bug (folding the PNG alpha channel into the grayscale value), not a task issue. The two trials that used torchvision-style `Normalize((0.1307,), (0.3081,))` split one fail / one pass, and the failing one is one of only two baseline failures we saw on this task — i.e. the preprocessing choice accounts for half of the failures that were not solver bugs. So the ambiguity is real and the one-line contract in this PR is the right fix.

---

## Comment on PR #2 (count-dataset-tokens: clarify token-counting semantics)

Solver-side evidence for the field-boundary ambiguity. In 5 failing trials (Seed 2.1 lite, several harness configurations) the solver computed **both** numbers — 79586 (fields tokenised separately) and 79566 (concatenated) — could not tell which one the grader wanted, and 4 of the 5 ran out of time while re-checking tokenizer behaviour; the fifth committed to 79566. Passing trials had simply picked "separately" first. Stating that the two fields are tokenised separately, as this PR does, removes the coin flip.

---

## Comment on issue #134 (fix-code-vulnerability: oracle fix left in git HEAD)

This also affects weaker models, not just leaderboard agents. In our baseline runs Seed 2.1 lite passed 9/9; **2 of those 9 passes came from the leftover git state**:

- Trial A (11 commands total): `git log --oneline -20` → `git diff bottle.py` (shows the removed `_hkey/_hval` validation as a deletion) → `git checkout bottle.py` (restores it) → writes `report.jsonl` → `pytest` → pass. No security analysis of any kind.
- Trial B: wrote its own `_hkey` fix, then ran `git checkout bottle.py`, which discarded that edit and restored the committed oracle version; what was graded is HEAD's code.

So the leak is reachable by an ordinary "let me see what changed" `git diff`, not only by agents that go looking for it. Committing the sed change (or `rm -rf .git` if history is not part of the task) fixes both cases.
