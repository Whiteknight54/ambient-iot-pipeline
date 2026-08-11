param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

function Test-UsablePythonCommand {
    param(
        [string]$CommandPath,
        [string[]]$Arguments = @("--version")
    )

    try {
        $null = & $CommandPath @Arguments 2>$null
        return $true
    } catch {
        return $false
    }
}

function Resolve-PythonInterpreter {
    param(
        [string]$RequestedPython
    )

    # If user provided a concrete path, trust it when valid.
    if (Test-Path $RequestedPython) {
        if (Test-UsablePythonCommand -CommandPath $RequestedPython) {
            return $RequestedPython
        }
    }

    $candidates = New-Object System.Collections.Generic.List[string]

    if ($RequestedPython -and $RequestedPython -ne "python") {
        $candidates.Add($RequestedPython)
    }

    try {
        $pythonCmd = Get-Command python -ErrorAction Stop
        if ($pythonCmd.Source -and ($pythonCmd.Source -notlike "*\\WindowsApps\\*")) {
            $candidates.Add($pythonCmd.Source)
        }
    } catch {}

    try {
        $pyCmd = Get-Command py -ErrorAction Stop
        if ($pyCmd.Source) {
            $candidates.Add($pyCmd.Source)
        }
    } catch {}

    $localPythonRoots = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $localPythonRoots) {
        $localPythonExes = Get-ChildItem -Path $localPythonRoots -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notlike "*\Lib\venv\*" } |
            Sort-Object FullName -Descending
        foreach ($entry in $localPythonExes) {
            $candidates.Add($entry.FullName)
        }
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -ieq "py") {
            if (Test-UsablePythonCommand -CommandPath "py" -Arguments @("-3.12", "--version")) {
                return "py -3.12"
            }
            if (Test-UsablePythonCommand -CommandPath "py" -Arguments @("-3", "--version")) {
                return "py -3"
            }
            if (Test-UsablePythonCommand -CommandPath "py" -Arguments @("--version")) {
                return "py"
            }
        } elseif (Test-UsablePythonCommand -CommandPath $candidate) {
            return $candidate
        }
    }

    throw "No usable Python interpreter found. Install Python 3.10+ or pass -Python with a valid python.exe path."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot ".venv"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
$resolvedPython = Resolve-PythonInterpreter -RequestedPython $Python

Write-Host "Using interpreter: $resolvedPython"

if (-not (Test-Path $pythonExe)) {
    if ($resolvedPython -like "py*") {
        $parts = $resolvedPython.Split(" ")
        & $parts[0] $parts[1] -m venv $venvPath
    } else {
        & $resolvedPython -m venv $venvPath
    }
}

if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment creation failed; expected interpreter at $pythonExe"
}

& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r (Join-Path $repoRoot "requirements.txt")

Write-Host "Environment ready at $venvPath"