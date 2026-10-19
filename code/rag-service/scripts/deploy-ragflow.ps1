param(
    [string]$InstallRoot = "$PSScriptRoot\.ragflow",
    [switch]$Start,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$version = "v1.0.0-rc2"
$repository = "https://github.com/infiniflow/ragflow.git"
$composeFile = Join-Path $InstallRoot "docker\docker-compose.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI 不存在。请先安装 Docker Desktop，并确认 docker compose 可用。"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git CLI 不存在，无法拉取官方 RAGFlow 仓库。"
}

if (-not (Test-Path $InstallRoot)) {
    git clone --branch $version --depth 1 $repository $InstallRoot
} else {
    $head = git -C $InstallRoot describe --tags --exact-match 2>$null
    if ($head -ne $version) {
        throw "已有 RAGFlow 目录不是固定版本 $version：$head"
    }
}

if (-not (Test-Path $composeFile)) {
    throw "找不到官方 Docker Compose 文件：$composeFile"
}

$envFile = Join-Path $InstallRoot "docker\.env"
if (-not (Test-Path $envFile)) {
    throw "RAGFlow .env 文件不存在，请按官方 docker/.env 配置后重试。"
}

if ($Stop) {
    docker compose --env-file $envFile -f $composeFile down
    exit $LASTEXITCODE
}

if ($Start) {
    docker compose --env-file $envFile -f $composeFile up -d
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    $healthUrl = "http://127.0.0.1:9380/api/v1/system/healthz"
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $healthUrl
            if ($response.StatusCode -eq 200) {
                Write-Output "RAGFlow $version is healthy: $healthUrl"
                exit 0
            }
        } catch {
            Start-Sleep -Seconds 5
        }
    }
    throw "RAGFlow 启动后 healthz 未在预期时间内返回 200。"
}

Write-Output "RAGFlow $version is ready at $InstallRoot"
Write-Output "Use -Start to run docker compose or -Stop to stop it."
