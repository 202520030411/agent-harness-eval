"""把 trials.json（tools/export_trajectories.py 在服务器上导出）和已有人工标注 CSV 灌进模板，生成单文件标注台。
用法：python tools/build_viewer.py reports/labeling_pack/trials.json reports/labeling_pack/viewer.html [reports/human_labels.csv]"""
import csv, json, sys
from pathlib import Path
data = Path(sys.argv[1]).read_text().replace("</script", "<\\/script")
seed = {}
if len(sys.argv) > 3 and Path(sys.argv[3]).exists():
    for r in csv.DictReader(open(sys.argv[3], encoding="utf-8-sig")):
        if r.get("human_primary"):
            seed[r["trial_id"]] = {"primary": r["human_primary"], "onset": r.get("human_onset", ""), "secondary": r.get("human_secondary", ""),
                                   "notes": r.get("human_notes", ""), "ci": r.get("clarity_intent_0_3", ""), "ct": r.get("clarity_target_0_3", ""),
                                   "reviewed": r.get("reviewed", "") == "yes" or not r.get("human_notes", "").startswith("[Claude")}
tpl = Path(__file__).with_name("viewer_template.html").read_text()
out = Path(sys.argv[2]); out.write_text(tpl.replace("__DATA__", data).replace("__SEED__", json.dumps(seed, ensure_ascii=False)))
print(out, out.stat().st_size // 1024, "KB; seeded", len(seed), "labels")
