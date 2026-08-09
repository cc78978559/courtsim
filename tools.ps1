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
        $LogDirectory = Join-Path $PSScriptRoot "work\logs\tooling"
        New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
        $SafeLabel = $Label -replace "[^A-Za-z0-9_.-]", "-"
        $LogPath = Join-Path $LogDirectory "${SafeLabel}-latest.log"
        $Output | Set-Content -LiteralPath $LogPath -Encoding UTF8
        Write-Output "${Label}: failed (full log: $LogPath)"
        if ($Output.Count -le 100) {
            $Output | Write-Output
        }
        else {
            $Output | Select-Object -First 20 | Write-Output
            Write-Output "... output truncated; showing final 80 lines ..."
            $Output | Select-Object -Last 80 | Write-Output
        }
        exit $ExitCode
    }
    Write-Output "${Label}: passed"
}

function Test-CompatiblePython {
    param(
        [string]$CommandPath,
        [string[]]$PrefixArguments = @()
    )
    try {
        & $CommandPath @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

if ($Command -eq "bootstrap") {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        $EnvironmentCreated = $false
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (
            $null -ne $PythonCommand -and
            (Test-CompatiblePython -CommandPath $PythonCommand.Source)
        ) {
            & $PythonCommand.Source -m venv (Join-Path $PSScriptRoot ".venv")
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            $EnvironmentCreated = $true
        }
        if (-not $EnvironmentCreated) {
            $PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
            if ($null -ne $PythonLauncher) {
                foreach ($Selector in @("-3.11", "-3.12", "-3.13", "-3.14", "-3")) {
                    if (
                        Test-CompatiblePython `
                            -CommandPath $PythonLauncher.Source `
                            -PrefixArguments @($Selector)
                    ) {
                        & $PythonLauncher.Source $Selector -m venv (Join-Path $PSScriptRoot ".venv")
                        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
                        $EnvironmentCreated = $true
                        break
                    }
                }
            }
        }
        if (-not $EnvironmentCreated) {
            throw "Python 3.11 or newer was not found through 'python' or the Windows 'py' launcher."
        }
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

if ($Command -eq "bootstrap-data") {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "Run '.\tools.cmd bootstrap' before installing optional data tools."
    }
    & $VenvPython -m pip install -r (Join-Path $PSScriptRoot "requirements\data.lock")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Output "data tooling complete: $VenvPython"
    exit 0
}

$script:Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"

switch ($Command) {
    "test" {
        Invoke-Python (@("-m", "pytest") + $RemainingArguments)
    }
    "coverage" {
        Invoke-Python (@("-m", "coverage", "run", "-m", "pytest") + $RemainingArguments)
        Invoke-Python @("-m", "coverage", "report")
    }
    "lint" {
        $LintTargets = if ($RemainingArguments.Count -gt 0) { $RemainingArguments } else { @(".") }
        Invoke-Python (@("-m", "ruff", "check") + $LintTargets)
    }
    "format" {
        $FormatTargets = if ($RemainingArguments.Count -gt 0) { $RemainingArguments } else { @(".") }
        Invoke-Python (@("-m", "ruff", "format") + $FormatTargets)
    }
    "typecheck" {
        Invoke-Python (@("-m", "mypy") + $RemainingArguments)
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
    "check-static" {
        Invoke-QuietPython "format" @("-m", "ruff", "format", "--check", ".")
        Invoke-QuietPython "lint" @("-m", "ruff", "check", ".")
        Invoke-QuietPython "typecheck" @("-m", "mypy")
    }
    "check-unit" {
        Invoke-QuietPython "unit-tests" @("-m", "pytest", "-q", "-m", "not slow")
    }
    "check-fast" {
        Invoke-QuietPython "format" @("-m", "ruff", "format", "--check", ".")
        Invoke-QuietPython "lint" @("-m", "ruff", "check", ".")
        Invoke-QuietPython "typecheck" @("-m", "mypy")
        Invoke-QuietPython "unit-tests" @("-m", "pytest", "-q", "-m", "not slow")
    }
    "check-slow" {
        Invoke-QuietPython "slow-tests" @("-m", "pytest", "-q", "-m", "slow")
    }
    "check-franchise" {
        Invoke-QuietPython "franchise-tests" @("-m", "pytest", "-q", "-m", "franchise")
    }
    "hydrate-long-test" {
        Invoke-Python @(
            "-m",
            "courtsim",
            "verify",
            "experiments\manifests\nba-v6-long-holdout-inputs-v1.json"
        )
        Write-Output "long-test inputs are present and hash-verified"
    }
    default {
        $CourtSimArguments = @("-m", "courtsim", $Command) + $RemainingArguments
        Invoke-Python $CourtSimArguments
    }
}

exit 0
