#!/bin/bash
# SMOKE-02 复验（revision 5 代码）：Linux + Docker Compose 路径 B 离线部署
set -u
R=/home/user/预算管理平台; D=$1
q() { docker compose -p smoke02r5 exec -T db psql -U budget -d budget -tAc "$1"; }
echo "== $(date -Is) 前端生产构建"; (cd $R/app/frontend && npm run build >/dev/null 2>&1); echo exit=$?
grep -c "身份切换\|dev-login\|login-as" $R/app/backend/app/static/assets/*.js | awk -F: '{s+=$2} END {print "dev-switch strings in bundle:", s}'
echo "== docker build"; docker build -q -f $R/deploy/Dockerfile -t budget-app:latest $R >/dev/null; echo exit=$?
echo "== docker save"; docker save budget-app:latest -o $D/images/app.tar; echo exit=$?
docker rmi -f budget-app:latest >/dev/null; echo "== docker load"; docker load -i $D/images/app.tar; echo exit=$?
cd $D; docker compose -p smoke02r5 down -v >/dev/null 2>&1
echo "== docker compose up -d"; docker compose -p smoke02r5 up -d 2>&1 | tail -2; echo exit=$?
timeout 180 bash -c 'until [ "$(docker compose -p smoke02r5 ps --format "{{.Health}}" | sort -u | tr -d "\n")" = "healthy" ]; do sleep 3; done'
echo "== ps"; docker compose -p smoke02r5 ps --format "{{.Service}} {{.State}} {{.Health}} {{.Ports}}"
echo "== migration"; q "select version_num from alembic_version"; q "select column_name from information_schema.columns where table_name='import_batch' and column_name='data_year'"
echo "== health $(curl -s -o /dev/null -w '%{http_code}' http://localhost:8100/api/health)"
echo "== dev login-as $(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8100/api/dev/login-as -H 'content-type: application/json' -d '{"user_id":1}')"
echo "== db port published: [$(docker compose -p smoke02r5 port db 5432 2>/dev/null)]"
echo "== write data via 钉钉替身 H5 login"; rm -f $D/ck2.txt
curl -s -c $D/ck2.txt -X POST http://localhost:8100/api/auth/dingtalk/h5 -H 'content-type: application/json' -d '{"auth_code":"h5-linxiao"}' | cut -c1-120; echo
echo "before restart: $(q "select count(*) from app_user"),$(q "select count(*) from user_role"),$(q "select count(*) from user_session")"
echo "== docker compose restart"; docker compose -p smoke02r5 restart 2>&1 | tail -2; echo exit=$?
timeout 180 bash -c 'until [ "$(docker compose -p smoke02r5 ps --format "{{.Health}}" | sort -u | tr -d "\n")" = "healthy" ]; do sleep 3; done'
docker compose -p smoke02r5 ps --format "{{.Service}} {{.State}} {{.Health}}"
echo "after restart: $(q "select count(*) from app_user"),$(q "select count(*) from user_role"),$(q "select count(*) from user_session")"
echo "== health $(curl -s -o /dev/null -w '%{http_code}' http://localhost:8100/api/health); me(old cookie) $(curl -s -b $D/ck2.txt -o /dev/null -w '%{http_code}' http://localhost:8100/api/me)"
