# 安装 Claude Code（Windows，PowerShell）
# 用法：右键「开始」→ Windows PowerShell，执行：
#   powershell -ExecutionPolicy Bypass -File .\安装ClaudeCode.ps1
# 本脚本只使用官方安装地址；所在地区不受支持时会停止并说明原因，不做任何绕过。

$ErrorActionPreference = 'Stop'
Write-Host '== 1/4 检查系统 ==' -ForegroundColor Cyan
$os = [Environment]::OSVersion.Version
if (-not [Environment]::Is64BitOperatingSystem) { Write-Host '需要 64 位 Windows。' -ForegroundColor Red; exit 1 }
Write-Host "Windows 版本：$os（64 位）"

Write-Host '== 2/4 检查 Git（可选，拉取 GitHub 仓库需要）==' -ForegroundColor Cyan
if (Get-Command git -ErrorAction SilentlyContinue) { git --version }
else { Write-Host '未检测到 Git。建议安装：https://git-scm.com/downloads/win（不影响本次安装）' -ForegroundColor Yellow }

Write-Host '== 3/4 下载官方安装程序 ==' -ForegroundColor Cyan
$tmp = Join-Path $env:TEMP 'claude-install.ps1'
try {
  Invoke-WebRequest -Uri 'https://claude.ai/install.ps1' -OutFile $tmp -UseBasicParsing
} catch {
  Write-Host "下载失败：$($_.Exception.Message)" -ForegroundColor Red
  Write-Host '请检查网络后重试。' ; exit 1
}
$head = Get-Content $tmp -TotalCount 5 -Raw
if ($head -match '<!DOCTYPE html|<html' -or (Get-Content $tmp -Raw) -match 'unavailable in region') {
  Remove-Item $tmp -Force
  Write-Host ''
  Write-Host '下载到的是网页而不是安装程序：Claude 在你当前所在的网络地区不可用（App unavailable in region）。' -ForegroundColor Red
  Write-Host '这不是脚本或 Windows 的问题，换安装方式也会被同样拦截。'
  Write-Host '支持地区列表：https://www.anthropic.com/supported-countries'
  Write-Host '可改用浏览器里的 claude.ai/code 云端会话继续开发。'
  exit 2
}

Write-Host '== 4/4 运行安装程序 ==' -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File $tmp
Remove-Item $tmp -Force -ErrorAction SilentlyContinue

$bin = Join-Path $env:USERPROFILE '.local\bin'
if (-not (($env:Path -split ';') -contains $bin)) { $env:Path = "$env:Path;$bin" }
if (Get-Command claude -ErrorAction SilentlyContinue) {
  claude --version
  Write-Host ''
  Write-Host '安装完成。请关闭并重新打开 PowerShell，然后：' -ForegroundColor Green
  Write-Host '  cd 你的项目文件夹'
  Write-Host '  claude        （首次运行会打开浏览器登录）'
} else {
  Write-Host "安装程序已运行，但当前窗口找不到 claude 命令。请重新打开 PowerShell 后执行 claude --version；仍找不到时，把 $bin 加入系统 PATH。" -ForegroundColor Yellow
}
