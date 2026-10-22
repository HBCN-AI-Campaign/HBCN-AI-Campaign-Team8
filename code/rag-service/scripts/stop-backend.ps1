param([int]$Port = 8011)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "data\backend-$Port.pid"
if (-not (Test-Path -LiteralPath $pidFile)) { throw '未找到本模块启动记录，未停止任何进程' }
$processId = [int](Get-Content -LiteralPath $pidFile)
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
if (-not $listener -or $listener.OwningProcess -ne $processId -or $processInfo.CommandLine -notmatch "uvicorn app.main:app.*--port $Port(\s|$)") { throw '端口或进程身份发生变化，未停止任何进程' }
Stop-Process -Id $processId
Write-Output 'RAG 已停止；如有处理中任务，重启后标记为失败，可通过 retry 接口重试'
