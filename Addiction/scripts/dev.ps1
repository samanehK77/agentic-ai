<#
.SYNOPSIS
  Small helper for the daily development commands of MindEvidence Lab (Windows PowerShell 5.1+ or PowerShell 7).

.DESCRIPTION
  Usage (from the project folder "Addiction"):   .\scripts\dev.ps1 <command> [extra arguments]

    up        start PostgreSQL in Docker          (docker compose up -d)
    migrate   apply the database migrations       (alembic upgrade head)
    seed      load the 10 synthetic patients      (python -m db.seed)
    ingest    ingest the PDFs in data\papers      (python -m app.ingestion; add --dry-run to preview)
    embed     embed the chunks for search         (python -m app.embedding; needs requirements-embeddings.txt)
    api       start the API on http://localhost:8001   (uvicorn, no --reload)
    web       start the frontend on http://localhost:8000
    test      run the test suite                  (pytest -q; live tests stay skipped)
    diagnose  health checks without secrets       (python -m app.diagnostics; add --deep only after approving a real model call)
    help      show this text

  The script never reads or writes your .env file. (Docker Compose and the application read it themselves.)
  Extra arguments are passed on, for example:   .\scripts\dev.ps1 ingest --dry-run
  It only wraps commands you could type yourself; it needs the virtual environment in backend\.venv (see docs\SETUP.md).
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Command = "help",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest = @()
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

function Show-Help { Get-Help $PSCommandPath -Detailed | Out-String | Write-Host }

function Require-Venv {
    if (-not (Test-Path $Python)) {
        throw "The virtual environment is missing ($Python). Create it first: cd backend; python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt  (see docs\SETUP.md)"
    }
}

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments, [string]$WorkDir)
    Push-Location $WorkDir
    try {
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "'$Exe $($Arguments -join ' ')' failed with exit code $LASTEXITCODE." }
    } finally { Pop-Location }
}

switch ($Command.ToLowerInvariant()) {
    "up"       { Invoke-Checked "docker" (@("compose", "up", "-d") + $Rest) $Root; Invoke-Checked "docker" @("compose", "ps") $Root }
    "migrate"  { Require-Venv; Invoke-Checked $Python (@("-m", "alembic", "upgrade", "head") + $Rest) $Backend }
    "seed"     { Require-Venv; Invoke-Checked $Python (@("-m", "db.seed") + $Rest) $Backend }
    "ingest"   { Require-Venv; Invoke-Checked $Python (@("-m", "app.ingestion") + $Rest) $Backend }
    "embed"    { Require-Venv; Invoke-Checked $Python (@("-m", "app.embedding") + $Rest) $Backend }
    "api"      { Require-Venv; Invoke-Checked $Python (@("-m", "uvicorn", "app.main:app", "--host", "localhost", "--port", "8001") + $Rest) $Backend }
    "web"      { Require-Venv; Invoke-Checked $Python (@("serve.py") + $Rest) $Frontend }
    "test"     { Require-Venv; Invoke-Checked $Python (@("-m", "pytest", "-q") + $Rest) $Backend }
    "diagnose" { Require-Venv; Invoke-Checked $Python (@("-m", "app.diagnostics") + $Rest) $Backend }
    "help"     { Show-Help }
    default    { Write-Host "Unknown command '$Command'.`n"; Show-Help; exit 2 }
}
