# 合成题的公共底座（QWEN_PLAN §4.1）：每道题的 Dockerfile 都 FROM 它，再拷自己的工作区文件、跑自己的初始化脚本。
# 在 Hetzner 上构建一次：docker build -t qsynth-base:1 -f base.Dockerfile .
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git sqlite3 curl ca-certificates tmux \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.4.1 \
    && git config --system user.email "dev@example.com" && git config --system user.name "dev" \
    && mkdir -p /logs /app
WORKDIR /app
