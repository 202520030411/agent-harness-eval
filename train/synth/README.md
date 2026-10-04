# 训练阶段执行手册（QWEN_PLAN §4.1；D-059 / D-060）

```
出题 ──▶ 构建 / 查重 / 校验 / 划分 ──▶ 采样（原版 Qwen × H2 × 训练题 3 次）──▶ 规则筛选导出 ──▶ LoRA SFT ──▶ 同一服务挂两份权重 ──▶ 原版 vs LoRA 同时评测
```

| 步 | 在哪 | 命令 | 检查点 |
|---|---|---|---|
| 1 出题 | Hetzner | `source ~/.secrets.env && PYTHONPATH=. .venv/bin/python train/synth/generate.py --out /root/work/train/synth_specs --per-family 25 --concurrency 12` | 结尾一行的花费（试点 0.062 美元 / 题） |
| 2 构建→查重→校验→划分 | Hetzner | `bash train/synth/after_gen.sh`（出题结束自动开始） | `synth_split.json` 里的合格数、训练 / 留出数；查重丢掉的题 |
| 3 起服务 | Pod | `bash gpu_bootstrap.sh`；Hetzner 上建隧道 `127.0.0.1:8000` | `/v1/models` 有 coder30b |
| 4 采样 | Hetzner | `bash tools/launch_job.sh qroll-h2-synth-train` | 通过率（原版在训练题上）、有多少题至少过 1 次 |
| 4b 第二轮（带提示，D-061） | Hetzner | `bash tools/launch_job.sh qroll-h2-synth-train-hint`；基础设施报错用 `bash tools/resume_jobs.sh <job>` 补跑（D-062） | 同时跑多个 job 前核对总并发 ≤ Docker 网络数（已改成 1024 个：`tools/fix_docker_pools.sh`） |
| 4c 排序检验（D-064） | Hetzner | Seed lite × 留出题 × 2（`qcheck-seed-synth-heldout`，用 ARK key 启动，不进训练） | Seed 与原版 Qwen 的通过率差 |
| 5 导出 | Hetzner | `bash train/export_sft.sh` → `sft_plain.jsonl`（第一轮）、`sft_all.jsonl`（两轮）、`sft_meta.md` | 各轮保留条数与丢弃原因；按技能族、难度档的构成 |
| 6 测速 | Pod（先停 vLLM） | `python sft_train.py --data sft_all.jsonl --out /workspace/ckpt/speedtest --device-map cuda --drop-long --max-len 32768 --max-steps 3 --grad-accum 1 --thinking default` | 每步秒数、显存 |
| 7 训练两个 LoRA（D-063） | Pod | 同一组超参（r 16、α 32、lr 1e-4、2 epoch、grad-accum 8）：`--data sft_plain.jsonl --out /workspace/ckpt/coderplain`，再 `--data sft_all.jsonl --out /workspace/ckpt/coderlora` | loss 下降；两个适配器目录 |
| 8 服务 | Pod | `bash serve_lora.sh coderlora=/workspace/ckpt/coderlora coderplain=/workspace/ckpt/coderplain` | `SERVE_LORA_OK`（每个适配器在温度 0 下至少一题与原版不同） |
| 9 评测 | Hetzner | `bash tools/launch_job.sh qeval-base-synth qeval-plain-synth qeval-lora-synth qeval-base-tb qeval-lora-tb`（五个同时） | 然后 `PYTHONPATH=. .venv/bin/python tools/qeval_report.py` |

数据规矩：训练样本里的每个 assistant token 都是 Qwen 自己当时生成的（`metadata.all_messages` 原样导出），不蒸馏；TB 2.1 全部题只做评测。

## RL（D-072：PSP 式 GRPO，从原版起步）

```
选 16 道训练题 ──▶ 当前策略每题做 8 次（H2）──▶ 判分 0/1 ──▶ 组内 advantage ──▶ Pod 上一次 LoRA 更新 ──▶ 挂新策略 ──▶ 下一步
        ▲ 最近一组不带提示全挂的题：gpt-6-sol 读这组失败写 3–6 条规则放题面最前（留在上下文、不进 loss）
```

| 步 | 在哪 | 命令 | 检查点 |
|---|---|---|---|
| 0 试点（决定提示方式） | Hetzner | `bash train/after_psp_pilot.sh`（规则 → 等评测挂上原版 → `qpilot-psp-rules` → 报告） | `reports/psp_pilot/summary.md` 最后一行的决定（A ≥ 15% → `--hint-mode rules`，否则 teacher） |
| 1 冒烟 | Hetzner（评测、试点都结束后） | `PYTHONPATH=. .venv/bin/python train/rl/grpo_loop.py --hint-mode rules --rl-dir /root/work/rl_smoke --prefix smoke --steps 2 --tasks-per-step 4 --attempts 4 --concurrency 16 --min-signal-groups 1 --only-tasks <4 道上一轮有对有错的题>` | 两步都走完；`lora_b` > 0；超长丢弃的比例 |
| 2 正式 | Hetzner（tmux） | `PYTHONPATH=. .venv/bin/python train/rl/grpo_loop.py --hint-mode <试点结果> --rl-dir /root/work/rl --prefix rl --steps 20 --budget-usd 120 > /root/work/rl/loop.log 2>&1` | `python3 tools/rl_status.py /root/work/rl` |
| 3 评测 | Hetzner + Pod | 同一个 vLLM 挂原版 + coderteach + 最终 RL 适配器，留出合成题 37 × 3 与 TB 30 × 4 同时跑 | `tools/qeval_report.py` |

止损（自动）：第 1 步有信号的组 < 4；最近 3 步平均通过率比最初 3 步低 10 pp；平均输出 token 翻倍；花费超过 `--budget-usd`。
中途断了直接重跑同一条命令：状态在 `<rl-dir>/state.json`，已完成的阶段会跳过；每步的适配器（含 Adam 状态）都拷回 `<rl-dir>/adapters/`。
