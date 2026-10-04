#!/bin/bash
# GPU 机器（Runpod，1×H200 141 GB，Container Disk 200 GB）一键准备：装 vLLM、下载 Qwen3-Coder-30B-A3B-Instruct、起 vLLM。
# 同一张卡顺序做：服务（harness 实验、rollout）→ 停服务训练 LoRA → 带 LoRA 重起服务评测。
# 用法：nohup bash gpu_bootstrap.sh > /workspace/logs/bootstrap.log 2>&1 &    （幂等；各步日志在 /workspace/logs）
set -euo pipefail
mkdir -p /workspace/logs /workspace/models /workspace/ckpt
cd /workspace
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1

echo "[$(date +%H:%M:%S)] step 1: install into /workspace/venv"
# 镜像的系统 Python 受 PEP 668 保护（不许直接 pip 装包）→ 用独立 venv；uv 装得快。
# 固定装 vLLM 的 CUDA 12.9 版：PyPI 默认包按 CUDA 13 编译，而 RunPod 常见的 570 驱动只支持到 12.8
# （2026-09-26 第一次就因此起不来）。12.9 编译的包在 12.x 驱动和更新的驱动上都能跑。
# “装好了”的判定是真往 GPU 上放一个数：import 不碰 GPU，torch.cuda.is_available() 在驱动不匹配时也照样返回 True。
VLLM_VERSION=0.30.0
V=/workspace/venv
if ! $V/bin/python -c "import vllm, torch; torch.ones(1, device='cuda')" 2>/dev/null; then
  rm -rf $V
  python -m venv $V
  $V/bin/pip install -q -U pip uv > /workspace/logs/pip.log 2>&1
  $V/bin/uv pip install --python $V/bin/python \
      "https://github.com/vllm-project/vllm/releases/download/v${VLLM_VERSION}/vllm-${VLLM_VERSION}+cu129-cp38-abi3-manylinux_2_28_x86_64.whl" \
      huggingface_hub hf_transfer \
      --extra-index-url https://download.pytorch.org/whl/cu129 --index-strategy unsafe-best-match >> /workspace/logs/pip.log 2>&1
fi
export PATH=$V/bin:$PATH
python -c "import vllm, torch; x = torch.ones(2, device='cuda'); print('vllm', vllm.__version__, '| torch', torch.__version__, '| cuda', torch.version.cuda, '| gpu ok', float(x.sum()) == 2.0)"

echo "[$(date +%H:%M:%S)] step 2: download model"
M=/workspace/models/Qwen3-Coder-30B-A3B-Instruct
if [ ! -f $M/.download_done ]; then
  python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-Coder-30B-A3B-Instruct', local_dir='$M', max_workers=16)" \
    > /workspace/logs/download.log 2>&1
  touch $M/.download_done
fi
du -sh $M

echo "[$(date +%H:%M:%S)] step 3: start vLLM on 127.0.0.1:8000"
# 先不开 LoRA：MoE 模型挂 LoRA 的支持要在训练前用一个迷你适配器单独验证，别让它挡住 harness 实验。
# --enable-auto-tool-choice + qwen3_coder：给 qwen-code（H3）用模型原生的工具调用格式。
if ! curl -s localhost:8000/v1/models >/dev/null; then
  nohup vllm serve $M --served-model-name coder30b --port 8000 --host 127.0.0.1 \
      --max-model-len 131072 --gpu-memory-utilization 0.92 \
      --enable-auto-tool-choice --tool-call-parser qwen3_coder \
      > /workspace/logs/vllm.log 2>&1 &
fi
for i in $(seq 1 180); do curl -s localhost:8000/v1/models >/dev/null && break; sleep 5; done
curl -s localhost:8000/v1/models | python -c 'import json,sys; print("vllm ready:", [m["id"] for m in json.load(sys.stdin)["data"]])'
echo "[$(date +%H:%M:%S)] BOOTSTRAP DONE"
