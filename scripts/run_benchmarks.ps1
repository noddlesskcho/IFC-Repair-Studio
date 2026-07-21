param([Parameter(Mandatory=$true)][string[]]$InputFile, [string]$Python = "python")
$ErrorActionPreference = "Stop"
foreach ($file in $InputFile) {
    & $Python -m ifc_context_repair.cli benchmark $file --profile "$file.profile"
}
