#!/bin/sh
# 每日备份（宿主 cron 01:30）：pg_dump + data/uploads 归档，保留 30 天；失败不删除旧备份
set -e
cd "$(dirname "$0")/.."
D=$(date +%Y%m%d); mkdir -p backup
if ! docker compose exec -T db pg_dump -Fc -U budget -d budget > backup/budget_$D.dump; then
  echo "$(date) pg_dump 失败" >> backup/backup_error.log; rm -f backup/budget_$D.dump; exit 1
fi
[ -d data/uploads ] && tar czf backup/uploads_$D.tar.gz data/uploads
find backup -maxdepth 1 -type f \( -name 'budget_*.dump' -o -name 'uploads_*.tar.gz' \) -mtime +30 -delete
