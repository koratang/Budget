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
rem 数据库程序与数据放在固定的纯英文目录（公用文档目录，所有账号可写），不受解压位置、中文路径、盘符映射影响
set "PGHOME=%PUBLIC%\BudgetTrialDB"
if not defined PUBLIC set "PGHOME=%SystemDrive%\BudgetTrialDB"
if not exist "%PGHOME%" mkdir "%PGHOME%" 2>nul
if not exist "%PGHOME%" (
  set "PGHOME=%SystemDrive%\BudgetTrialDB"
  mkdir "%SystemDrive%\BudgetTrialDB" 2>nul
)
rem copied.flag 在复制完整结束后才写，复制中断时下次会重新复制
if not exist "%PGHOME%\pgsql\copied.flag" (
  echo 准备数据库程序（首次约 10 秒）...
  xcopy "%ROOT%\pgsql" "%PGHOME%\pgsql\" /E /I /Q /Y /H >nul
  if errorlevel 1 goto :err_copy
  echo ok>"%PGHOME%\pgsql\copied.flag"
)
set "PG=%PGHOME%\pgsql\bin"
set "PGDATA=%PGHOME%\data"
echo 数据库目录：%PGHOME%
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
  rem 上次初始化中断留下的半成品目录会让 initdb 失败，先清掉（此时库还不存在，没有数据可丢）
  if exist "%PGDATA%" rmdir /s /q "%PGDATA%"
  del "%PGHOME%\seeded.flag" >nul 2>&1
  "%PG%\initdb" -D "%PGDATA%" -U postgres -A trust -E UTF8 --no-locale >"%PGHOME%\initdb.log" 2>&1
  if errorlevel 1 goto :err_initdb
)

"%PG%\pg_ctl" -D "%PGDATA%" status >nul 2>&1
if errorlevel 1 (
  echo [2/4] 启动数据库（端口 54329）...
  "%PG%\pg_ctl" -D "%PGDATA%" -l "%PGHOME%\pg.log" -o "-p 54329 -h 127.0.0.1" -w start >nul
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
if not exist "%PGHOME%\seeded.flag" (
  echo 写入演示数据...
  "%PY%" -m scripts.seed
  if errorlevel 1 goto :err_migrate
  echo ok>"%PGHOME%\seeded.flag"
  if exist "%ROOT%\ops-history-2026.xlsx" (
    echo 导入 2026 年经营历史表...
    "%PY%" -m scripts.import_ops_history "%ROOT%\ops-history-2026.xlsx" --year 2026 --create-missing
  )
)
rem 模拟演示数据：2027 年度预算闭环与 2027 年 1–3 月实际等（已写过会自动跳过）
echo 写入模拟演示数据（首次约需 1 分钟）...
"%PY%" -m scripts.seed_demo
if errorlevel 1 goto :err_migrate

echo [4/4] 启动系统：浏览器将打开 http://localhost:8000
start "钉钉替身（试用版用，勿关）" /min "%PY%" -m uvicorn dingtalk_stub.main:app --host 127.0.0.1 --port 8090
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8000"
echo 关闭本窗口即停止系统；彻底停止数据库请运行「停止试用.bat」。
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:err_copy
echo 复制数据库程序到 %PGHOME% 失败。请确认磁盘空间充足、杀毒软件没有拦截后重试。
pause & exit /b 1
:err_initdb
echo 数据库初始化失败。下面是详细原因，请把整个窗口截图发给我：
echo ---------- initdb.log ----------
if exist "%PGHOME%\initdb.log" type "%PGHOME%\initdb.log"
echo ---------- 数据库程序自检 ----------
"%PG%\postgres" -V
echo 数据库目录：%PGHOME%
pause & exit /b 1
:err_pg
echo 数据库启动失败。若 54329 端口被占用，请先运行「停止试用.bat」。下面是详细原因，请把整个窗口截图发给我：
echo ---------- pg.log ----------
if exist "%PGHOME%\pg.log" type "%PGHOME%\pg.log"
echo ---------- 数据库程序自检 ----------
"%PG%\postgres" -V
echo 数据库目录：%PGHOME%
pause & exit /b 1
:err_migrate
echo 数据库结构更新或演示数据写入失败，请把上面的报错截图发给我。
pause & exit /b 1
