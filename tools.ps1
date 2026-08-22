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
$script:TimingEnabled = $false
$script:TimingStages = [System.Collections.Generic.List[object]]::new()
$script:TimingStartedAt = $null

function Write-TimingReceipt {
    if (-not $script:TimingEnabled) { return }
    $OutputDirectory = Join-Path $PSScriptRoot "work\metrics"
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    $OutputPath = Join-Path $OutputDirectory "check-timed-latest.json"
    $CompletedAt = [DateTimeOffset]::Now
    $Commit = @(& git rev-parse HEAD 2>$null)
    $Dirty = @(& git status --porcelain=v1 2>$null).Count -gt 0
    $Receipt = [ordered]@{
        schema = "courtsim-local-check-timing-v1"
        command = "check-timed"
        started_at = $script:TimingStartedAt.ToString("o")
        completed_at = $CompletedAt.ToString("o")
        elapsed_seconds = [math]::Round(
            ($CompletedAt - $script:TimingStartedAt).TotalSeconds,
            3
        )
        commit = if ($Commit.Count -gt 0) { $Commit[-1] } else { $null }
        dirty = $Dirty
        stages = @($script:TimingStages)
    }
    $Receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    Write-Output "timing-receipt: $OutputPath"
}

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
    $Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $Output = @(& $script:Python @PythonArguments 2>&1)
    $ExitCode = $LASTEXITCODE
    $Stopwatch.Stop()
    if ($script:TimingEnabled) {
        $script:TimingStages.Add([ordered]@{
            name = $Label
            elapsed_seconds = [math]::Round($Stopwatch.Elapsed.TotalSeconds, 3)
            passed = $ExitCode -eq 0
        })
    }
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
        Write-TimingReceipt
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

function Test-DevelopmentEnvironment {
    param([string]$PythonPath)
    if (-not (Test-Path -LiteralPath $PythonPath)) { return $false }
    & $PythonPath -c "import coverage, courtsim, mypy, pytest, ruff" *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    & $PythonPath -m pip check *> $null
    return $LASTEXITCODE -eq 0
}

if ($Command -eq "bootstrap") {
    $RepairRequested = $RemainingArguments -contains "--repair"
    $UnexpectedBootstrapArguments = @($RemainingArguments | Where-Object { $_ -ne "--repair" })
    if ($UnexpectedBootstrapArguments.Count -gt 0) {
        throw "Unsupported bootstrap arguments: $($UnexpectedBootstrapArguments -join ' ')"
    }
    if ($RepairRequested -and (Test-DevelopmentEnvironment -PythonPath $VenvPython)) {
        Write-Output "development environment is healthy: $VenvPython"
        exit 0
    }
    if (
        $RepairRequested -and
        (Test-Path -LiteralPath (Join-Path $PSScriptRoot ".venv")) -and
        -not (Test-DevelopmentEnvironment -PythonPath $VenvPython)
    ) {
        $QuarantineRoot = Join-Path $PSScriptRoot "work\quarantine"
        New-Item -ItemType Directory -Force -Path $QuarantineRoot | Out-Null
        $QuarantinePath = Join-Path `
            $QuarantineRoot `
            ("venv-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
        if (Test-Path -LiteralPath $QuarantinePath) {
            throw "Virtual-environment quarantine path already exists: $QuarantinePath"
        }
        Move-Item -LiteralPath (Join-Path $PSScriptRoot ".venv") -Destination $QuarantinePath
        Write-Output "quarantined invalid environment: $QuarantinePath"
    }
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

function Invoke-FastCheck {
    param([string[]]$PytestArguments = @())
    Invoke-QuietPython "format" @("-m", "ruff", "format", "--check", ".")
    Invoke-QuietPython "lint" @("-m", "ruff", "check", ".")
    Invoke-QuietPython "typecheck" @("-m", "mypy")
    Invoke-QuietPython "unit-tests" (@("-m", "pytest", "-q", "-m", "not slow") + $PytestArguments)
}

function Get-ChangedPaths {
    $Paths = @(& git diff --name-only --diff-filter=ACMR HEAD)
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect changed Git paths." }
    $Paths += @(& git ls-files --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect untracked Git paths." }
    return @($Paths | Where-Object { $_ } | Sort-Object -Unique)
}

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
        Invoke-FastCheck -PytestArguments $RemainingArguments
    }
    "check-timed" {
        $script:TimingEnabled = $true
        $script:TimingStartedAt = [DateTimeOffset]::Now
        Invoke-FastCheck -PytestArguments $RemainingArguments
        Write-TimingReceipt
    }
    "check-changed" {
        $ChangedPaths = @(Get-ChangedPaths)
        if ($ChangedPaths.Count -eq 0) {
            Write-Output "check-changed: no working-tree changes"
            break
        }
        $PythonPaths = @($ChangedPaths | Where-Object { $_ -like "*.py" })
        $SourceOrConfigurationChanged = @(
            $ChangedPaths | Where-Object {
                $_ -like "src/*" -or
                $_ -eq "pyproject.toml" -or
                $_ -like "requirements/*" -or
                $_ -like "tools*"
            }
        ).Count -gt 0
        if ($SourceOrConfigurationChanged) {
            Write-Output "check-changed: production or tooling change; running full fast gate"
            Invoke-FastCheck -PytestArguments $RemainingArguments
            break
        }
        $ChangedTests = @($PythonPaths | Where-Object { $_ -like "tests/*" })
        if ($ChangedTests.Count -eq 0) {
            Write-Output "check-changed: no Python changes"
            break
        }
        Invoke-QuietPython "format" (@("-m", "ruff", "format", "--check") + $PythonPaths)
        Invoke-QuietPython "lint" (@("-m", "ruff", "check") + $PythonPaths)
        Invoke-QuietPython "typecheck" @("-m", "mypy")
        Invoke-QuietPython "changed-tests" (
            @("-m", "pytest", "-q", "-m", "not slow") + $ChangedTests + $RemainingArguments
        )
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
