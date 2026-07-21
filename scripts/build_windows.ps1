param([string]$Python = "py", [switch]$Clean)
$ErrorActionPreference = "Stop"
if ($Clean) {
    foreach ($path in @("build", "dist")) {
        $resolved = Join-Path $PSScriptRoot "..\$path"
        if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
    }
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[ui,test,build]"
& $Python -m pytest
& $Python -m PyInstaller --noconfirm --clean --windowed --name IFCRepairStudio `
    --icon assets\ifc_repair_studio.ico `
    --add-data "assets\ifc_repair_studio.ico;assets" `
    --collect-binaries ifcopenshell --collect-data ifcopenshell `
    --hidden-import ifcopenshell.validate --hidden-import ifcopenshell.geom `
    scripts\gui_entry.py
Write-Host "Build created under dist\IFCContextRepair. Test it on a clean Windows VM before release."
