@echo off
chcp 65001 >nul
rem 每日备份（任务计划程序 01:30 调用）：pg_dump 自定义格式 + uploads 归档，保留 30 天；失败不删除旧备份
setlocal
set PGBIN=C:\Program Files\PostgreSQL\18\bin
set BACKUP_DIR=%~dp0..\..\backup
set DATA_DIR=%~dp0..\..\app\backend\data
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set D=%%i
"%PGBIN%\pg_dump.exe" -Fc -h 127.0.0.1 -U budget -d budget -f "%BACKUP_DIR%\budget_%D%.dump" || (echo %date% %time% pg_dump 失败>>"%BACKUP_DIR%\backup_error.log" & exit /b 1)
powershell -NoProfile -Command "if (Test-Path '%DATA_DIR%\uploads') { Compress-Archive -Force -Path '%DATA_DIR%\uploads' -DestinationPath '%BACKUP_DIR%\uploads_%D%.zip' }"
powershell -NoProfile -Command "Get-ChildItem '%BACKUP_DIR%' -File | Where-Object { $_.Name -match '^(budget_|uploads_)' -and $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item"
