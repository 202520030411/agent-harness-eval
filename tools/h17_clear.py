from pathlib import Path
from agenteval.adapters.harbor import load_job
from agenteval.report.stats import paired_compare
amb = {t.strip() for t in open("experiments/task_list_ambiguous.txt") if t.strip()}
J = "/root/work/jobs/"
clear = lambda ts: [t for t in ts if t.task_name not in amb]
gate_on = lambda t: bool(((t.metadata.get("patched") or {}).get("contract_gate") or {}).get("on"))
def cmp(tb, tc):
    r = paired_compare([(t.task_name, t.passed) for t in tb], [(t.task_name, t.passed) for t in tc])
    return f"tasks={r['n_tasks']:2d} n={len(tb)}/{len(tc)} delta={r['delta_pp']:+.1f} ci=[{r['ci95_pp'][0]:+.1f},{r['ci95_pp'][1]:+.1f}]"
e4b, e4c = clear(load_job(Path(J+"e4-baseline-rerun"))), clear(load_job(Path(J+"e4-contract")))
pb, pc = clear(load_job(Path(J+"e4p-baseline"))), clear(load_job(Path(J+"e4p-contract-v1")))
hb, hc = clear(load_job(Path(J+"h17-baseline"))), clear(load_job(Path(J+"h17-conditional")))
print("clear E4 (contract v1)        ", cmp(e4b, e4c))
print("clear E4p (contract v1)       ", cmp(pb, pc))
on_tasks = {t.task_name for t in hc if gate_on(t)}
maj = {k for k in on_tasks if sum(gate_on(t) for t in hc if t.task_name == k) >= 2}
print("clear H17, gate-on trials only (contract side), on majority-on tasks", sorted(maj))
print("   ", cmp([t for t in hb if t.task_name in maj], [t for t in hc if t.task_name in maj and gate_on(t)]))
print("clear H17, gate-off trials only (upstream + gate latency)")
print("   ", cmp(hb, [t for t in hc if not gate_on(t)]))
print("pooled clear, contract v1 (E4+E4p)", cmp(e4b + pb, e4c + pc))
print("--- E4p per clear task where contract lost:")
for task in sorted({t.task_name for t in pb}):
    b = [t.passed for t in pb if t.task_name == task]; c = [t.passed for t in pc if t.task_name == task]
    hb_ = [t.passed for t in hb if t.task_name == task]; hc_on = [t.passed for t in hc if t.task_name == task and gate_on(t)]
    if sum(c) < sum(b):
        print(f"  {task:32s} E4p {sum(b)}/{len(b)}->{sum(c)}/{len(c)}   H17 base {sum(hb_)}/{len(hb_)}, H17 contract(gate-on) {sum(hc_on)}/{len(hc_on)}")
