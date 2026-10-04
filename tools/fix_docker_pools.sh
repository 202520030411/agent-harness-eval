#!/bin/bash
# Docker 默认只能分出约 31 个内部网络，Harbor 每个 trial 占一个 → 同时跑 > ~28 个 trial 就报
# “all predefined address pools have been fully subnetted”（2026-09-27 两轮采样同时跑时踩坑）。改成 172.20.0.0/14 切 /24 = 1024 个。
# 要重启 Docker：只在没有容器运行时执行（否则正在跑的 trial 会断）。镜像不受影响。
set -euo pipefail
n=$(docker ps -q | wc -l)
[ "$n" -eq 0 ] || { echo "refusing: $n containers still running"; exit 1; }
docker network prune -f > /dev/null
cat > /etc/docker/daemon.json <<'JSON'
{
  "default-address-pools": [{"base": "172.20.0.0/14", "size": 24}]
}
JSON
systemctl restart docker
sleep 3
docker network create pooltest > /dev/null
docker network inspect pooltest --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'
docker network rm pooltest > /dev/null
docker images qsynth-base:1 --format '{{.Repository}}:{{.Tag}} still present'
