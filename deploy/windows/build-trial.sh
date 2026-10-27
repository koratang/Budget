#!/bin/sh
# 在可联网的 Linux 构建机上生成 Windows 免安装试用包（内置 Python 3.14 嵌入版、PostgreSQL 18 便携版、VC++ 运行库）
# 输出：deploy/trial/预算管理平台-试用版.zip（内含 BudgetTrial 文件夹；解压到纯英文路径后双击「启动试用.bat」）
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYV=3.14.10
PGV=18.6-1
WORK="$ROOT/deploy/trial/work"
PKG="$WORK/BudgetTrial"
rm -rf "$WORK" && mkdir -p "$WORK/dl" "$PKG/python" "$PKG/app/backend"
cd "$WORK/dl"
curl -fsSLO "https://www.python.org/ftp/python/$PYV/python-$PYV-embed-amd64.zip"
curl -fsSLO "https://get.enterprisedb.com/postgresql/postgresql-$PGV-windows-x64-binaries.zip"
python3 -m pip download msvc-runtime --no-deps --only-binary=:all: --platform win_amd64 --python-version 3.14 --implementation cp -d .
unzip -q "python-$PYV-embed-amd64.zip" -d "$PKG/python"
unzip -q "postgresql-$PGV-windows-x64-binaries.zip" 'pgsql/bin/*' 'pgsql/lib/*' 'pgsql/share/*' 'pgsql/server_license.txt' -d "$PKG"
# PostgreSQL 便携版不含 VC++ 运行库，随包放入 bin
unzip -q msvc_runtime-*.whl -d msvc
cp msvc/*.data/data/Scripts/msvcp140*.dll msvc/*.data/data/Scripts/vcruntime140*.dll msvc/*.data/data/Scripts/concrt140.dll "$PKG/pgsql/bin/"
# Windows 版依赖装入嵌入式 Python，并让它能导入后端代码
python3 -m pip install -r "$ROOT/app/backend/requirements.txt" --target "$PKG/python/Lib/site-packages" \
  --only-binary=:all: --platform win_amd64 --python-version 3.14 --implementation cp
rm -rf "$PKG/python/Lib/site-packages/bin"
printf 'python314.zip\r\n.\r\nLib\\site-packages\r\n..\\app\\backend\r\nimport site\r\n' > "$PKG/python/python314._pth"
# 前端开发构建（保留开发身份切换）+ 后端代码
(cd "$ROOT/app/frontend" && npm ci && npm run build:dev)
B="$ROOT/app/backend"
cp -r "$B/app" "$B/alembic" "$B/alembic.ini" "$B/dingtalk_stub" "$B/scripts" "$PKG/app/backend/"
find "$PKG/app" -name __pycache__ -prune -exec rm -rf {} +
rm -rf "$PKG/app/backend/app/data"
cp "$ROOT/deploy/windows/trial/"* "$PKG/"
(cd "$WORK" && rm -f ../预算管理平台-试用版.zip && python3 -m zipfile -c ../预算管理平台-试用版.zip BudgetTrial)  # zipfile 为中文文件名写入 UTF-8 标记，Windows 解压不乱码
rm -rf "$WORK"
ls -lh "$ROOT/deploy/trial/预算管理平台-试用版.zip"
