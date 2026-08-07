param([string]$Python = "py", [switch]$Clean)
$ErrorActionPreference = "Stop"

$originalPath = $env:PATH
try {
    # Android Studio's JBR directory contains private api-ms-win-* DLLs.  If it
    # appears on PATH, PyInstaller can mistake them for Windows runtime files.
    $cleanPath = @($env:SystemRoot, (Join-Path $env:SystemRoot "System32"))
    $cleanPath += @(
        $originalPath -split ";" | Where-Object {
            $_ -and -not (
                $_ -match "(?i)Android[\\/]Android Studio" -and
                $_ -match "(?i)[\\/](jbr|jre)([\\/]|$)"
            )
        }
    )
    $env:PATH = ($cleanPath | Select-Object -Unique) -join ";"

    if ($Clean) {
        foreach ($path in @("build", "dist")) {
            $resolved = Join-Path $PSScriptRoot "..\$path"
            if (Test-Path -LiteralPath $resolved) {
                Remove-Item -LiteralPath $resolved -Recurse -Force
            }
        }
    }

    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with exit code $LASTEXITCODE" }
    & $Python -m pip install -e ".[ui,test,build,diagnostics]"
    if ($LASTEXITCODE -ne 0) { throw "dependency installation failed with exit code $LASTEXITCODE" }
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "tests failed with exit code $LASTEXITCODE" }
    & $Python -m PyInstaller --noconfirm --clean packaging\IFCSGRepairAssistant-1.0.0.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    Write-Host "Build created under dist\IFCSGRepairAssistant-1.0.0."
}
finally {
    $env:PATH = $originalPath
}
