$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\ianli\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$App = Join-Path $Root "app.py"

if (-not (Test-Path $Python)) {
    Write-Host "Bundled Python not found: $Python"
    exit 1
}

Set-Location $Root
& $Python -m streamlit run $App --server.address 127.0.0.1 --server.port 8501
