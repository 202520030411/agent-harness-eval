# cancel-async-tasks: instruction omits the cancellation semantics the verifier checks (queued tasks must not start; cleanup itself awaits; interrupt arrives as an external SIGINT)

**Task:** `cancel-async-tasks` (terminal-bench 2.1). Label: bug.

## Summary

`instruction.md` describes cancellation in one sentence: *"Sometimes I cancel runs via keyboard interrupt but I want the tasks' cleanup code to still run."* The verifier checks three stronger, unstated requirements, and `task.toml` says the queued-task behaviour is the point of the task ("including the edge case of queued tasks") — but that edge case never appears in the agent-facing instruction.

## Details

`tests/test_outputs.py::test_tasks_cancel_above_max_concurrent` runs `test.py --n-tasks 3 --max-concurrent 2`, sends `SIGINT` to the process after 0.5 s, and asserts exactly `2 × "Task started."` and `2 × "Cleaned up."`. That encodes:

1. tasks still waiting in the queue must **not** be started once the interrupt arrives;
2. every started task's cleanup must run to completion — and in `test.py` the `finally:` block itself `await`s (`asyncio.sleep(1)`), so cancellation has to wait for cleanup rather than just trigger it;
3. the interrupt is a real `SIGINT` delivered from outside, through `asyncio.run(main())`, not a `task.cancel()` call.

None of the three is derivable from the instruction. A solver that reads it literally implements "let cleanup run" (which works when cleanup is synchronous) and fails only on requirement 1/2, which is the "common gotcha" the test's own docstring describes.

## Evidence

15 baseline trials with one model (Seed 2.1 lite, Terminus 2, unchanged task): 5 pass, 10 fail. **8 of the 10 failures fail only `test_tasks_cancel_above_max_concurrent`** (the other 2 failed everything — the solver wrote a non-coroutine `run_tasks`, a genuine model error).

With the instruction rewritten to state the three requirements — no change to tests, image or reference solution — the same model passed **3/3**. Rewritten paragraph used:

> Required behaviour (this is what is checked):
> * Tasks are started in list order and at most `max_concurrent` are running at any moment; when one finishes, the next queued task starts.
> * Sometimes I cancel runs via keyboard interrupt (SIGINT / KeyboardInterrupt, sent to the process while tasks are running). In that case: cancel every task that has already started, do **not** start any task still waiting in the queue, and wait until the cleanup code (the `finally:` block, which itself awaits) of every started task has finished before the program exits. Cleanup must run exactly once per started task.
> * The caller runs it as `asyncio.run(main())` where `main` simply awaits `run_tasks(...)`.

## Suggested fix

Add the cancellation contract to `instruction.md` (a shorter version of the paragraph above is enough: "on KeyboardInterrupt, cancel running tasks, do not start queued ones, and await each started task's cleanup before returning"). If the intent is to keep the gotcha implicit, the instruction should at least say that queued tasks must not start after an interrupt, since that is what `task.toml` says the task evaluates.
