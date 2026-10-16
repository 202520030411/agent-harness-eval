"""最终报告的逐题核对：哪些题两臂通过次数不同、那些 trial 里有没有逐行追加（提醒有没有可能起作用）、提醒触发了几次。"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/root/work/agent_harness")
from tools.loop_cycle import observe_jobs  # noqa: E402

for ds in ["tb", "heldout"]:
    base = observe_jobs([f"loop-final-{ds}-base"])
    cand = observe_jobs([f"loop-final-{ds}-v0-c04"])
    agg = defaultdict(lambda: {"b": 0, "c": 0, "b_app": 0, "c_app": 0, "c_nudges": 0})
    for r in base:
        a = agg[r["task"]]; a["b"] += bool(r.get("passed")); a["b_app"] += (r.get("append_turns") or 0) >= 3
    for r in cand:
        a = agg[r["task"]]; a["c"] += bool(r.get("passed")); a["c_app"] += (r.get("append_turns") or 0) >= 3
        try:
            res = json.loads((Path("/root/work/jobs") / r["job"] / r["trial"] / "result.json").read_text())
            a["c_nudges"] += len(((res.get("agent_result") or {}).get("metadata") or {}).get("patched", {}).get("append_nudges") or [])
        except Exception:  # noqa: BLE001
            pass
    diff = {t: a for t, a in agg.items() if a["b"] != a["c"]}
    print(f"== {ds}: {len(agg)} tasks; passes v0 {sum(a['b'] for a in agg.values())}, c04 {sum(a['c'] for a in agg.values())}; "
          f"tasks where c04 sent >=1 append nudge: {sum(1 for a in agg.values() if a['c_nudges'])}")
    print("   task | v0 passes | c04 passes | v0 trials with >=3 append turns | c04 trials with >=3 append turns | nudges sent in c04")
    for t, a in sorted(diff.items(), key=lambda kv: kv[1]["c"] - kv[1]["b"], reverse=True):
        print(f"   {t[:45]:45s} | {a['b']} | {a['c']} | {a['b_app']} | {a['c_app']} | {a['c_nudges']}")
