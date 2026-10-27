@echo off
chcp 65001 >nul
rem 预算管理平台 · Windows 原生启动（路径 A）。首次运行前请按 部署说明.md 安装 Python 与 PostgreSQL 并填写 app\backend\.env
cd /d "%~dp0..\..\app\backend"
if not exist .venv\Scripts\python.exe (
  echo 正在创建运行环境…
  py -3.14 -m venv .venv || python -m venv .venv
  if exist ..\..\wheels\win_amd64 (
    .venv\Scripts\pip install --no-index --find-links ..\..\wheels\win_amd64 -r requirements.txt
  ) else (
    .venv\Scripts\pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
  )
)
.venv\Scripts\alembic upgrade head || goto :err
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
goto :eof
:err
echo 数据库迁移失败，请检查 .env 中的 DATABASE_URL 与 PostgreSQL 服务。
pause
