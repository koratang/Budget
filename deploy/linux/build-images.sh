#!/bin/sh
# 在可联网的构建机上执行：构建前端 → 构建应用镜像 → 导出离线镜像 tar（服务器只需 docker load）
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
(cd "$ROOT/app/frontend" && npm ci && npm run build)
docker build -f "$ROOT/deploy/Dockerfile" -t budget-app:latest "$ROOT"
mkdir -p "$ROOT/deploy/images"
docker save budget-app:latest -o "$ROOT/deploy/images/app.tar"
docker save postgres:18.6-bookworm -o "$ROOT/deploy/images/postgres.tar"
echo "离线镜像已生成：deploy/images/app.tar、deploy/images/postgres.tar"
