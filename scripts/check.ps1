param(
    [switch]$SkipPreCommit,
    [switch]$CheckStaged,
    [switch]$Fix
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

if ($Fix) {
    # -Fix: ローカル向けに自動修正する（CI では未指定で --check 検証のままにする）
    Invoke-Step "ruff check --fix" {
        & $python -m ruff check --fix .
    }

    Invoke-Step "ruff format" {
        & $python -m ruff format .
    }
}
else {
    Invoke-Step "ruff check" {
        & $python -m ruff check .
    }

    Invoke-Step "ruff format --check" {
        & $python -m ruff format --check .
    }
}

Invoke-Step "pytest" {
    & $python -m pytest
}

if (-not $SkipPreCommit) {
    Invoke-Step "pre-commit run --all-files" {
        & $python -m pre_commit run --all-files
    }
}

Invoke-Step "git diff --check" {
    git diff --check
}

if ($CheckStaged) {
    Invoke-Step "git diff --cached --check" {
        git diff --cached --check
    }
}

Invoke-Step "git status --short" {
    git status --short
}
