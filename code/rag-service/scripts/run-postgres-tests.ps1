param()

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$ragRoot = Split-Path $PSScriptRoot -Parent
$previousOptIn = $env:HBCN_TEST_POSTGRES
$locationPushed = $false

try {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Create code/rag-service/.venv and install requirements-dev.txt before running integration tests."
    }
    if (-not $env:RAG_DATABASE_URL) {
        throw "Set RAG_DATABASE_URL to a local disposable PostgreSQL database named hbcn_rag_test."
    }
    Push-Location $ragRoot
    $locationPushed = $true
    & $python (Join-Path $PSScriptRoot "postgres_test_prereqs.py")
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL safety preflight failed." }

    $env:HBCN_TEST_POSTGRES = "1"
    & $python -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL integration suite failed." }
}
finally {
    if ($locationPushed) { Pop-Location }
    if ($null -eq $previousOptIn) {
        Remove-Item Env:HBCN_TEST_POSTGRES -ErrorAction SilentlyContinue
    } else {
        $env:HBCN_TEST_POSTGRES = $previousOptIn
    }
}
