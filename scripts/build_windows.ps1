param([string]$Python = "py", [switch]$Clean)
$ErrorActionPreference = "Stop"
if ($Clean) {
    foreach ($path in @("build", "dist")) {
        $resolved = Join-Path $PSScriptRoot "..\$path"
        if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
    }
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[ui,test,build,diagnostics]"
& $Python -m pytest
& $Python -m PyInstaller --noconfirm --clean packaging\IFCSGRepairAssistant-1.0.0.spec
Write-Host "Build created under dist\IFCSGRepairAssistant-1.0.0."
