# [terminal-bench] configure-git-webserver: instruction says login setup is out of scope, but verify.sh requires a `user` account that can ssh

**Task:** `configure-git-webserver` (terminal-bench 2.1)

**Problem.** The instruction ends with "I'll setup login with the server to work, you don't have to worry about that." `tests/verify.sh` then copies a public key into `/home/user/.ssh`, `chown -R user:user`, and runs `git clone user@localhost:/git/server`. If the solver takes the instruction literally and does not create a `user` account (the image has none), the clone fails, no push happens, and the curl check returns 404 — even though the solver's own end-to-end test (clone/push/curl as another local user) succeeded.

**Evidence.** In the observed failure the agent explicitly checked `id user` → "no such user", cited the instruction's sentence, and decided not to create the account; the verifier's stderr shows `fatal: not a git repository` from the failed clone before the 404.

**Suggested fix.** Either drop that sentence and say "the grader will connect as the local user `user` over ssh; make sure that works", or have `verify.sh` create the account itself before installing the key.
