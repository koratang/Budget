@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "HOME_DIR=%CD%"
set "ROOT=%CD%"
set "DRV="
if exist "%HOME_DIR%\data\drive.txt" set /p DRV=<"%HOME_DIR%\data\drive.txt"
if defined DRV if exist "%DRV%\python\python.exe" set "ROOT=%DRV%\"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PGHOME=%PUBLIC%\BudgetTrialDB"
if not exist "%PGHOME%\data\PG_VERSION" set "PGHOME=%SystemDrive%\BudgetTrialDB"
if exist "%PGHOME%\pgsql\bin\pg_ctl.exe" "%PGHOME%\pgsql\bin\pg_ctl" -D "%PGHOME%\data" stop -m fast
taskkill /fi "WINDOWTITLE eq 钉钉替身*" >nul 2>&1
if defined DRV (
  subst %DRV% /d >nul 2>&1
  del "%HOME_DIR%\data\drive.txt" >nul 2>&1
)
echo 已停止。数据保留在 %PGHOME%，下次运行「启动试用.bat」继续使用。
pause
