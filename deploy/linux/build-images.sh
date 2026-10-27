#!/bin/sh
# 在可联网的构建机上执行：构建前端 → 构建应用镜像 → 导出离线镜像 tar（服务器只需 docker load）
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
(cd "$ROOT/app/frontend" && npm ci && npm run build)
# 下载 Linux cp314 离线 wheel（国内可用 -i https://mirrors.aliyun.com/pypi/simple/）
mkdir -p "$ROOT/deploy/wheels/linux"
python3 -m pip download -r "$ROOT/app/backend/requirements.txt" -d "$ROOT/deploy/wheels/linux" --only-binary=:all: \
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --python-version 3.14 --implementation cp
docker build -f "$ROOT/deploy/Dockerfile" -t budget-app:latest "$ROOT"
mkdir -p "$ROOT/deploy/images"
docker save budget-app:latest -o "$ROOT/deploy/images/app.tar"
docker save postgres:18.6-bookworm -o "$ROOT/deploy/images/postgres.tar"
echo "离线镜像已生成：deploy/images/app.tar、deploy/images/postgres.tar"
