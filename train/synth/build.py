"""题目描述 JSON → Harbor 本地题目目录（QWEN_PLAN §4.1）。每题：task.toml、instruction.md、environment/（FROM qsynth-base:1 + 工作区文件
+ 初始化脚本）、tests/（test.sh + test_outputs.py，agent 看不到）、solution/solve.sh（给 oracle 校验用）。
用法：python train/synth/build.py --specs /root/work/train/synth_specs --out /root/work/train/synth_tasks
"""
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

TASK_TOML = """schema_version = "1.1"
artifacts = []

[task]
name = "synth/{name}"
description = "Synthetic training task ({family}, {domain})."
keywords = ["synthetic", "{family}"]

[metadata]
author_name = "agent_harness"
author_email = "unknown"
difficulty = "medium"
category = "{family}"
tags = ["synthetic", "{family}"]

[verifier]
timeout_sec = 300.0

[agent]
timeout_sec = 900.0

[environment]
build_timeout_sec = 900.0
cpus = 1
memory_mb = 2048
storage_mb = 10240
gpus = 0
allow_internet = true
"""

TEST_SH = """#!/bin/bash
# 隐藏测试：pytest 在底座镜像里已装好；结果写 /logs/verifier/reward.txt（1 = 通过）
cd /app
python3 -m pytest -q -rA /tests/test_outputs.py > /logs/verifier/pytest.txt 2>&1
rc=$?
tail -40 /logs/verifier/pytest.txt
if [ $rc -eq 0 ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
"""


def safe_rel(p: str) -> str:
    q = Path(p.lstrip("/").replace("app/", "", 1) if p.startswith("/app/") else p.lstrip("/"))
    if ".." in q.parts or not q.parts:
        raise ValueError(f"bad workspace path {p!r}")
    return str(q)


def build_one(spec: dict, out_root: Path) -> Path:
    m = spec["_meta"]
    name = f"{m['family']}--{spec['task_id']}"
    d = out_root / name
    (d / "environment" / "workspace").mkdir(parents=True, exist_ok=True)
    (d / "tests").mkdir(exist_ok=True); (d / "solution").mkdir(exist_ok=True)
    (d / "task.toml").write_text(TASK_TOML.format(name=name, family=m["family"], domain=m["domain"]))
    (d / "instruction.md").write_text(spec["instruction"].rstrip() + "\n")
    for rel, content in spec["workspace_files"].items():
        f = d / "environment" / "workspace" / safe_rel(rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content if isinstance(content, str) else json.dumps(content, indent=1))
    lines = ["FROM qsynth-base:1", "WORKDIR /app"]
    apt = [p for p in spec.get("apt_packages") or [] if p]
    pip = [p for p in spec.get("pip_packages") or [] if p]
    if apt:
        lines.append("RUN apt-get update && apt-get install -y --no-install-recommends " + " ".join(map(shlex.quote, apt))
                     + " && rm -rf /var/lib/apt/lists/*")
    if pip:
        lines.append("RUN pip install --no-cache-dir " + " ".join(map(shlex.quote, pip)))
    lines.append("COPY workspace/ /app/")
    if (spec.get("setup_script") or "").strip():
        (d / "environment" / "setup.sh").write_text(spec["setup_script"])
        lines += ["COPY setup.sh /tmp/setup.sh", "RUN cd /app && bash /tmp/setup.sh && rm /tmp/setup.sh"]
    (d / "environment" / "Dockerfile").write_text("\n".join(lines) + "\n")
    (d / "tests" / "test.sh").write_text(TEST_SH)
    (d / "tests" / "test_outputs.py").write_text(spec["tests"])
    sol = spec["solution"]
    (d / "solution" / "solve.sh").write_text(sol if sol.startswith("#!") else "#!/bin/bash\n" + sol)
    for f in (d / "tests" / "test.sh", d / "solution" / "solve.sh"):
        f.chmod(0o755)
    return d


def main(a) -> None:
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    ok = bad = 0
    for f in sorted(Path(a.specs).glob("*.json")):
        try:
            build_one(json.loads(f.read_text()), out); ok += 1
        except Exception as e:  # noqa: BLE001
            bad += 1; print(f"skip {f.name}: {e!r}"[:200])
    print(f"built {ok} tasks into {out} ({bad} skipped)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", required=True)
    ap.add_argument("--out", required=True)
    main(ap.parse_args())
