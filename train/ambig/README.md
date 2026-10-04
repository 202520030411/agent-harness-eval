# 针对性训练：题面缺约定时先查证据（2026-09-26 起）

> **⚠️ 历史记录，已被 `docs/QWEN_PLAN.md` 取代，不要照此执行（2026-09-26）。** 本文件保留的是计划的演变过程：其中的“查证据”训练目标、Seed 老师数据、2 张 H200、Qwen3.6 备选、OpenRouter 推理均已作废；当前唯一有效的计划见 `QWEN_PLAN.md` 开头的“当前状态”。


**动机（来自评测）：** 契约实验里模型列出的模糊点 80% 命中决定性细节，但强制逐点做决定后，命中时的通过率从 8/12 掉到 3/12（D-048/D-050）。识别不是瓶颈，“缺约定时怎么做决定”才是。harness 侧的提示救不了（D-047：多走一轮在时限下是负项），所以交给训练：让模型学会“约定不清 → 去环境里找证据 → 按证据做”。

**设计：** 训练题由 `generator.py` 合成：简单数据处理任务 + 题面缺一个约定（日期格式、分隔符、金额单位、字段命名、排序、区间开闭、缺失值），约定写在工作区某个文件里（配置 / 测试 / 示例 / 文档），另放无关文件。只有查了证据才可能答对 → **只用结果奖励**，不给“读了文件就加分”的过程奖励（防止走过场）。25% 是题面写明约定的清晰版对照。

```
训练：进程内环境（env.py，工作区是 dict，动作 list_dir / read_file / submit，≤10 轮，JSON 动作）
  老师 Seed 采样（rollout.py）──▶ 拒绝采样：通过 + 读过证据 + 无格式错误（sft_data.py）──▶ LoRA SFT（sft_train.py）
评测：同一生成器的留出种子导出成 Harbor 任务（export_harbor.py）──▶ Terminus 2 + Docker，与 TB 2.1 用同一条流水线
  主指标：留出合成题通过率；机制指标：交付前是否读过证据文件；迁移：TB 2.1 模糊题 14 道；不退化：清晰题 27 道
```

**防污染：** TB 2.1 的题只做评测，不进训练；训练与留出的合成题用不同的种子区间（`rollout.SPLITS`）。

## 运行手册

### 1. 服务器（Hetzner，已完成）
```bash
cd /root/work/agent_harness/train/ambig
source ~/.secrets.env
# 老师采样（Seed），--mix 混入 25% 清晰题
../../.venv/bin/python rollout.py --model openai/doubao-seed-2-1-lite-260915 --api-base https://ark.cn-beijing.volces.com/api/v3 \
    --api-key-env ARK_API_KEY --split train --n 200 --mix --out /root/work/train/teacher_b1.jsonl
../../.venv/bin/python sft_data.py /root/work/train/teacher_*.jsonl --out /root/work/train/sft.jsonl
# 留出题（Harbor 格式）+ oracle 自检
../../.venv/bin/python export_harbor.py --split heldout --n 60 --mix --out /root/work/train/harbor_ambig_heldout
```

### 2. GPU 机器（RunPod 安全云，1 个 Pod × 2 张 H200 141 GB；学生 Qwen3-Coder-30B-A3B-Instruct，备选 Qwen3.6-35B-A3B 只做摸底）
```bash
bash gpu_bootstrap.sh     # 装依赖、并行下载两个模型、GPU0 起 coder30b（:8000）、GPU1 起 qwen36（:8001）
# 为什么不用 Qwen3-8B：SETA（arXiv 2607.10891）报告其 TB 2.0 基线仅 3.6%，低于本实验 5% 的止损线
```

### 3. 服务器 → GPU 的隧道（评测在服务器上跑，Docker 在服务器）
```bash
# 在服务器上（需先把服务器的公钥放进 GPU 机器的 authorized_keys）
ssh -N -f -L 8000:127.0.0.1:8000 -p <GPU_SSH_PORT> <GPU_USER>@<GPU_HOST>
curl -s http://127.0.0.1:8000/v1/models
```

### 4. 摸底（阶段 0）
```bash
# 进程内环境（快，不起容器）
../../.venv/bin/python rollout.py --model openai/coder30b --api-base http://127.0.0.1:8000/v1 --api-key-env NONE \
    --split heldout --n 60 --mix --out /root/work/train/student_base_heldout.jsonl
# Terminus 2 + Harbor：合成留出题 + TB 2.1 41 题（配置见 experiments/configs/ambig-*.resolved.yaml）
```
止损：TB 2.1 基线 <5% 或 >60%，或学生在合成题上本来就查证据（没有可训练的缺口）→ 停。

### 5. 训练与评测
```bash
python sft_data.py teacher_*.jsonl --out sft.jsonl
CUDA_VISIBLE_DEVICES=1 python sft_train.py --data sft.jsonl --out /workspace/ckpt/coder30b-ambig --epochs 2 --targets attn --thinking default
# vLLM 重启并挂上 LoRA，然后用 --model openai/ambig 重跑第 4 步，对比训练前后；再做一次契约的拐杖判定
```
