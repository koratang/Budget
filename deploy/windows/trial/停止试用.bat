@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%CD%\pgsql\bin\pg_ctl" -D "%CD%\data\pg" stop -m fast
taskkill /fi "WINDOWTITLE eq 钉钉替身*" >nul 2>&1
echo 已停止。数据保留在 data 文件夹，下次运行「启动试用.bat」继续使用。
pause
