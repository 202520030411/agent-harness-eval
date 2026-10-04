# build-cython-ext: verifier runs the upstream pyknotid test suite unpinned, and one upstream test now fails even for the reference solution (task is currently unpassable)

**Task:** `build-cython-ext` (terminal-bench 2.1). Label: bug.

## Summary

`tests/test_outputs.py::test_pyknotid_repository_tests` clones `SPOCKnots/pyknotid` at tag `0.5.3` **at verification time** and runs its whole test suite (minus `test_random_curves.py` and `test_catalogue.py`) against whatever dependency versions are installed. The only pinned dependency is `numpy==2.3.0` (checked by `test_numpy_version`); everything the upstream tests import (sympy, networkx, scipy, …) floats. As of 2026-09-23, running the task's own reference solution in the shipped image (`alexgshaw/build-cython-ext:20251031`) yields:

- 10/11 verifier tests pass (imports, all three Cython extensions, the README snippet);
- `test_pyknotid_repository_tests` fails: inner run **17 passed, 1 failed** — `tests/test_spacecurve.py::test_reconstructed_space_curve`.

So the reference solution scores 0, and no solver can do better than the reference on this check.

## Details

- The verifier asserts only on the inner pytest's return code (`assert result.returncode == 0`), so the failing upstream test's traceback is not surfaced in the verifier log; the summary line is truncated inside pytest's assertion message. That makes the failure look like a solver error when it is an environment drift.
- Reproduction (reference solution applied, then the same command the verifier runs, with `-v`):

```
$ docker run --rm -v <task>/solution:/solution:ro alexgshaw/build-cython-ext:20251031 bash
# cd /app && bash /solution/solve.sh          # exit 0; installs pyknotid-0.5.3 plus unpinned deps:
#   ... networkx-3.7 planarity-1.0.0 sympy-1.14.0 ... (numpy stays 2.3.0, cython 3.1.3)
# git clone --depth 1 --branch 0.5.3 https://github.com/SPOCKnots/pyknotid.git /tmp/up
# cd /app/pyknotid && python -m pytest /tmp/up/tests --ignore .../test_random_curves.py --ignore .../test_catalogue.py
1 failed, 17 passed

FAILED tests/test_spacecurve.py::test_reconstructed_space_curve
    k2 = k.reconstructed_space_curve()
pyknotid/spacecurves/spacecurve.py:756: in reconstructed_space_curve
    return SpaceCurve(r.space_curve())
pyknotid/representations/representation.py:495: in space_curve
    g, lines, ... = self._construct_planar_graph()
pyknotid/representations/representation.py:338: in _construct_planar_graph
    pg = planarity.PGraph(g); pg.embed_drawplanar(); g = planarity.networkx_graph(pg)
    for node, data in g.nodes(data=True):
        y = data['pos']
E   KeyError: 'pos'
```

The failure is in the `planarity`/`networkx` code path (`planarity.networkx_graph` no longer populates the `pos` node attribute that pyknotid 0.5.3 reads), i.e. drift in dependencies the task never pins and that have nothing to do with the numpy-2.x compatibility or the Cython extensions the task is about.

- The instruction itself already acknowledges that parts of the upstream suite are dead/unstable (it excludes two files). The remaining tests are equally exposed to upstream and dependency drift because nothing is vendored or pinned.

## Suggested fix

Any of:

1. Vendor the upstream tests into `/tests` at a fixed commit and pin the dependencies the inner run needs (the task already pins numpy; pin the rest the same way), or
2. Exclude `test_reconstructed_space_curve` like the two files already excluded (cheapest; keeps the check meaningful for the Cython extensions, which the other verifier tests already cover directly), or
3. Have the verifier print the inner pytest output on failure so that drift of this kind is visible in the leaderboard logs.

Since the reference solution is also the oracle used to validate the task, re-running the oracle in CI would have caught this; that is the "oracle agent" check the Terminal-Bench 3.0 process now does.
