#!/bin/bash
# 出题结束后自动：构建 → 与 TB 查重 → oracle / nop 校验（同时）→ 合格题按技能族分成训练 / 留出，拷成两个 Harbor 数据集目录
cd /root/work/agent_harness
until [ -f /root/work/train/synth_gen.done ]; do sleep 20; done
echo "$(TZ=America/New_York date +%H:%M) generation done: $(tail -1 /root/work/train/synth_gen.log)"
.venv/bin/python train/synth/build.py --specs /root/work/train/synth_specs --out /root/work/train/synth_tasks
.venv/bin/python train/synth/similarity.py --tasks /root/work/train/synth_tasks --out /root/work/train/synth_similarity.json
echo "$(TZ=America/New_York date +%H:%M) validating"
for ag in oracle nop; do .venv/bin/harbor run -c experiments/configs/synth-val-$ag.resolved.yaml -y > /root/work/jobs/synth-val-$ag.log 2>&1 & done; wait
.venv/bin/python train/synth/collect_valid.py --oracle-job /root/work/jobs/synth-val-oracle --nop-job /root/work/jobs/synth-val-nop \
    --similarity /root/work/train/synth_similarity.json --tasks /root/work/train/synth_tasks --materialize /root/work/train/synth_split \
    --out /root/work/train/synth_split.json
echo "$(TZ=America/New_York date +%H:%M) READY"
touch /root/work/train/synth_ready.done
