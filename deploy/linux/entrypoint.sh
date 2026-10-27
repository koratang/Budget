#!/bin/sh
# 容器启动：等待数据库 → 执行迁移 → 启动单体服务（单进程）
set -e
for i in $(seq 1 60); do
  python -c "import psycopg,os;psycopg.connect(os.environ['DATABASE_URL'].replace('postgresql+psycopg','postgresql')).close()" 2>/dev/null && break
  echo "等待数据库就绪…($i)"; sleep 2
done
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
