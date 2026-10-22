param([int]$Port = 8011)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '先创建 .venv 并安装 requirements.txt' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "端口 $Port 已有服务，未停止或覆盖现有进程" }
$logs = Join-Path $root 'data'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$process = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port", '--workers', '1') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "backend-$Port.out.log") -RedirectStandardError (Join-Path $logs "backend-$Port.err.log") -PassThru
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($health.service -eq 'hbcn-rag-service') {
            $listener = Get-NetTCPConnection -LocalPort $Port -State Listen
            $listener.OwningProcess | Set-Content -LiteralPath (Join-Path $logs "backend-$Port.pid")
            Write-Output "RAG 已启动，PID=$($listener.OwningProcess)，地址 http://127.0.0.1:$Port/docs；就绪状态需检查 /api/v1/ready"
            exit 0
        }
    } catch { }
    if ($process.HasExited) { throw "RAG 启动退出，请检查 data/backend-$Port.err.log" }
    Start-Sleep -Seconds 1
}
throw "RAG 启动超时，请检查 data/backend-$Port.err.log，进程未被强制结束"
