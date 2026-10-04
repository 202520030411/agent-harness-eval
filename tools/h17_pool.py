from pathlib import Path
from agenteval.adapters.harbor import load_job
from agenteval.report.stats import paired_compare

amb = {t.strip() for t in open("experiments/task_list_ambiguous.txt") if t.strip()}
J = "/root/work/jobs/"
cache = {}


def L(j):
    if j not in cache:
        cache[j] = [t for t in load_job(Path(J + j)) if t.task_name in amb]
    return cache[j]


def gate_on(t):
    return bool(((t.metadata.get("patched") or {}).get("contract_gate") or {}).get("on"))


def cmp(tb, tc):
    r = paired_compare([(t.task_name, t.passed) for t in tb], [(t.task_name, t.passed) for t in tc])
    return f"tasks={r['n_tasks']:2d} n={len(tb)}/{len(tc)} delta={r['delta_pp']:+.1f} ci=[{r['ci95_pp'][0]:+.1f},{r['ci95_pp'][1]:+.1f}]"


batches = [("E4", "e4-baseline-rerun", "e4-contract"), ("E4t", "e4t-baseline", "e4t-contract"),
           ("E4p", "e4p-baseline", "e4p-contract-v1"), ("H17", "h17-baseline", "h17-conditional")]
pb, pc = [], []
for name, b, c in batches:
    print(f"{name:5s}", cmp(L(b), L(c)))
    pb += L(b); pc += L(c)
pb3 = [t for t in pb if not t.job_name.startswith("h17")]; pc3 = [t for t in pc if not t.job_name.startswith("h17")]
print("pooled E4+E4t+E4p      ", cmp(pb3, pc3))
print("pooled +H17 (all trials)", cmp(pb, pc))
pc_on = pc3 + [t for t in L("h17-conditional") if gate_on(t)]
print("pooled +H17 (gate-on only on contract side)", cmp(pb, pc_on))

print("--- per ambiguous task: passes/trials baseline -> contract, per batch")
for task in sorted(amb):
    row = []
    for name, b, c in batches:
        xb = [t for t in L(b) if t.task_name == task]; xc = [t for t in L(c) if t.task_name == task]
        row.append(f"{name}:{sum(t.passed for t in xb)}/{len(xb)}->{sum(t.passed for t in xc)}/{len(xc)}" if xb else f"{name}:-")
    g = [gate_on(t) for t in L("h17-conditional") if t.task_name == task]
    print(f"{task:28s} gate {sum(g)}/{len(g)}  " + "  ".join(row))

print("--- H17 ambiguous-arm timeouts / gate latency")
for t in L("h17-conditional"):
    g = (t.metadata.get("patched") or {}).get("contract_gate") or {}
    if t.status == "agent_timeout" or not t.passed:
        print(f"  {t.task_name:28s} passed={t.passed} status={t.status} gate_on={g.get('on')} gate_latency={g.get('latency_sec')} turns={t.n_episodes}")
for t in L("h17-baseline"):
    if t.status == "agent_timeout" or not t.passed:
        print(f"  [base] {t.task_name:28s} passed={t.passed} status={t.status} turns={t.n_episodes}")
