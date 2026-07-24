[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$Command = "doctor",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArguments
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$Wheelhouse = Join-Path $PSScriptRoot "tools\wheelhouse"

function Invoke-Python {
    param([string[]]$PythonArguments)
    & $script:Python @PythonArguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Invoke-QuietPython {
    param(
        [string]$Label,
        [string[]]$PythonArguments
    )
    $Output = @(& $script:Python @PythonArguments 2>&1)
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        $Output | Write-Output
        exit $ExitCode
    }
    Write-Output "${Label}: passed"
}

if ($Command -eq "bootstrap") {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        & python -m venv (Join-Path $PSScriptRoot ".venv")
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    $script:Python = $VenvPython
    $LocalWheels = @(Get-ChildItem -LiteralPath $Wheelhouse -Filter "*.whl" -ErrorAction SilentlyContinue)
    if ($LocalWheels.Count -gt 0) {
        Invoke-Python @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "-r", "requirements\build.lock")
        Invoke-Python @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "-r", "requirements\dev.lock")
    }
    else {
        Invoke-Python @("-m", "pip", "install", "-r", "requirements\build.lock")
        Invoke-Python @("-m", "pip", "install", "-r", "requirements\dev.lock")
    }
    Invoke-Python @("-m", "pip", "install", "--no-build-isolation", "--no-deps", "-e", ".")
    Write-Output "bootstrap complete: $VenvPython"
    exit 0
}

$script:Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"

switch ($Command) {
    "test" {
        Invoke-Python @("-m", "pytest")
    }
    "coverage" {
        Invoke-Python @("-m", "coverage", "run", "-m", "pytest")
        Invoke-Python @("-m", "coverage", "report")
    }
    "lint" {
        Invoke-Python @("-m", "ruff", "check", ".")
    }
    "format" {
        Invoke-Python @("-m", "ruff", "format", ".")
    }
    "typecheck" {
        Invoke-Python @("-m", "mypy")
    }
    "check" {
        Invoke-QuietPython "format" @("-m", "ruff", "format", "--check", ".")
        Invoke-QuietPython "lint" @("-m", "ruff", "check", ".")
        Invoke-QuietPython "typecheck" @("-m", "mypy")
        Invoke-QuietPython "tests" @("-m", "coverage", "run", "-m", "pytest", "-q")
        $Coverage = @(& $script:Python -m coverage report --format=total 2>&1)
        $CoverageExitCode = $LASTEXITCODE
        if ($CoverageExitCode -ne 0) {
            $Coverage | Write-Output
            exit $CoverageExitCode
        }
        Write-Output "coverage: $($Coverage[-1])%"
    }
    "check-fast" {
        Invoke-QuietPython "format" @("-m", "ruff", "format", "--check", ".")
        Invoke-QuietPython "lint" @("-m", "ruff", "check", ".")
        Invoke-QuietPython "typecheck" @("-m", "mypy")
        Invoke-QuietPython "tests" @("-m", "pytest", "-q")
    }
    default {
        $CourtSimArguments = @("-m", "courtsim", $Command) + $RemainingArguments
        Invoke-Python $CourtSimArguments
    }
}

exit 0
