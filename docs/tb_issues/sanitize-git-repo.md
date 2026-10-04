# sanitize-git-repo: verifier diffs against a hard-coded commit SHA, so removing the secrets from history (which the instruction asks for) makes the verifier error out

**Task:** `sanitize-git-repo` (terminal-bench 2.1). Label: bug.

## Summary

The secrets live in committed history. The instruction says *"Please ensure that the sensitive values are not present in the repository after the sanitization"*, which a careful solver reads as "including history", so it rewrites history and prunes. `tests/test_outputs.py` then does

```python
# Specific commit before any changes were made
commit = repo.commit("d6987af002b122fef54bc0be402062c76488a4d9")
diff = commit.diff(None)
```

After a history rewrite plus `gc`/`prune` that object no longer exists, GitPython raises `ValueError: ... d6987af002b122fef54bc0be402062c76488a4d9 missing`, and the trial gets reward 0 even when the working tree is exactly what the task wants.

## Details

- The instruction's only constraint on scope is *"be careful to not delete or modify any files that are not contaminated"* — about files, not history. Nothing says the original commit objects must remain reachable.
- The verifier's other checks (placeholders present, secrets absent, untouched files unchanged) are all satisfiable after a rewrite; only the hard-coded SHA lookup is not.
- Whether a rewrite passes therefore depends on an invisible detail: `git filter-branch` keeps `refs/original/*` (object still reachable → passes), but deleting that backup ref or running `git filter-repo` / `gc --prune` (the standard "make sure it is really gone" steps) removes it → fails.

## Evidence

Across our runs of this task (several agent configurations, mostly Seed 2.1 lite via Terminus 2, plus one trial with gpt-6-sol), **17 of 25 failing trials died on that exact line** (`d6987af… missing`), including the gpt-6-sol trial. The remaining 8 failures were genuine (a secret was still present). In the failing trajectories the solver had rewritten history precisely because it took "not present in the repository" to include history.

## Suggested fix

Either of:

1. State the constraint in `instruction.md`: "Only change the working tree; do not rewrite git history" (then the hard-coded SHA is fair), or
2. Make the verifier independent of history: keep a pristine copy of the tree outside the repo (or a tarball baked into the image) and diff the working tree against that; optionally also assert that `git log -p` contains no secret if history rewriting is the intended solution.

Right now the most thorough reading of the instruction is the one that cannot pass.
