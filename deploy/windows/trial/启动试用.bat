@echo off
chcp 65001 >nul
rem 预算管理平台 · Windows 免安装试用版（开发配置 + 演示数据，仅本机使用）
cd /d "%~dp0"
set "HOME_DIR=%CD%"
if not exist "%HOME_DIR%\data" mkdir "%HOME_DIR%\data"
rem 内置数据库不支持中文或空格路径：把本文件夹映射成一个空闲盘符（subst，无需管理员），之后全部从纯英文路径运行
set "DRV="
if exist "%HOME_DIR%\data\drive.txt" set /p DRV=<"%HOME_DIR%\data\drive.txt"
if defined DRV if not exist "%DRV%\python\python.exe" set "DRV="
if not defined DRV for %%D in (B R S T U V W X Y) do if not defined DRV if not exist %%D:\ subst %%D: "%HOME_DIR%" >nul 2>&1 && set "DRV=%%D:"
if defined DRV (
  >"%HOME_DIR%\data\drive.txt" echo %DRV%
  cd /d %DRV%\
)
set "ROOT=%CD%"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
echo 运行目录：%ROOT%
set "PG=%ROOT%\pgsql\bin"
set "PGDATA=%ROOT%\data\pg"
set "PY=%ROOT%\python\python.exe"
set APP_ENV=dev
set DEV_IDENTITY_SWITCH=true
set "DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:54329/budget"
set "DATA_DIR=%ROOT%\data\files"
set "DINGTALK_BASE_URL=http://127.0.0.1:8090"
set DINGTALK_APP_KEY=stub
set DINGTALK_APP_SECRET=stub
set DINGTALK_AGENT_ID=10001
set DINGTALK_CORP_ID=ding-stub
if not exist "%ROOT%\data" mkdir "%ROOT%\data"

if not exist "%PGDATA%\PG_VERSION" (
  echo [1/4] 首次运行：初始化本地数据库...
  "%PG%\initdb" -D "%PGDATA%" -U postgres -A trust -E UTF8 --no-locale >"%ROOT%\data\initdb.log" 2>&1
  if errorlevel 1 goto :err_initdb
)

"%PG%\pg_ctl" -D "%PGDATA%" status >nul 2>&1
if errorlevel 1 (
  echo [2/4] 启动数据库（端口 54329）...
  "%PG%\pg_ctl" -D "%PGDATA%" -l "%ROOT%\data\pg.log" -o "-p 54329 -h 127.0.0.1" -w start >nul
  if errorlevel 1 goto :err_pg
)

"%PG%\psql" -h 127.0.0.1 -p 54329 -U postgres -tAc "select 1 from pg_database where datname='budget'" | findstr 1 >nul
if errorlevel 1 (
  "%PG%\createdb" -h 127.0.0.1 -p 54329 -U postgres budget
  if errorlevel 1 goto :err_pg
)

echo [3/4] 更新数据库结构...
cd /d "%ROOT%\app\backend"
"%PY%" -m alembic upgrade head
if errorlevel 1 goto :err_migrate
if not exist "%ROOT%\data\seeded.flag" (
  echo 写入演示数据...
  "%PY%" -m scripts.seed
  if errorlevel 1 goto :err_migrate
  echo ok>"%ROOT%\data\seeded.flag"
  if exist "%ROOT%\ops-history-2026.xlsx" (
    echo 导入 2026 年经营历史表...
    "%PY%" -m scripts.import_ops_history "%ROOT%\ops-history-2026.xlsx" --year 2026 --create-missing
  )
)

echo [4/4] 启动系统：浏览器将打开 http://localhost:8000
start "钉钉替身（试用版用，勿关）" /min "%PY%" -m uvicorn dingtalk_stub.main:app --host 127.0.0.1 --port 8090
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8000"
echo 关闭本窗口即停止系统；彻底停止数据库请运行「停止试用.bat」。
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:err_initdb
echo 数据库初始化失败，详见 data\initdb.log。请把本文件夹放在纯英文路径下（例如 D:\BudgetTrial）后重试。
pause & exit /b 1
:err_pg
echo 数据库启动失败，详见 data\pg.log。若 54329 端口被占用，请先运行「停止试用.bat」。
echo ---------- data\pg.log 内容 ----------
if exist "%ROOT%\data\pg.log" type "%ROOT%\data\pg.log"
echo ---------- 当前路径：%ROOT% ----------
echo ---------- 数据库程序自检 ----------
"%PG%\postgres" -V
pause & exit /b 1
:err_migrate
echo 数据库结构更新或演示数据写入失败，请把上面的报错截图发给我。
pause & exit /b 1
