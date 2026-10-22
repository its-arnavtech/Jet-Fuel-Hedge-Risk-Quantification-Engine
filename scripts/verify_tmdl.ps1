param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot), [string]$AssemblyFolder)
$ErrorActionPreference = 'Stop'
if ($AssemblyFolder) {
    $pbiBin = (Resolve-Path -LiteralPath $AssemblyFolder).Path
} else {
    $pbiPackage = Get-AppxPackage -Name 'Microsoft.MicrosoftPowerBIDesktop'
    if ($null -eq $pbiPackage) { throw 'Supply -AssemblyFolder with official Microsoft TOM NuGet assemblies' }
    $pbiBin = Join-Path $pbiPackage.InstallLocation 'bin'
}
foreach ($assembly in @('Microsoft.AnalysisServices.Core.dll', 'Microsoft.AnalysisServices.Tabular.dll')) {
    [void][System.Reflection.Assembly]::LoadFrom((Join-Path $pbiBin $assembly))
}
$modelFolder = Join-Path $ProjectRoot 'powerbi\JetFuelHedgeRisk\JetFuelHedgeRisk.SemanticModel\definition'
$database = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeDatabaseFromFolder($modelFolder)
$modelHashes = [ordered]@{}
Get-ChildItem -LiteralPath $modelFolder -Filter '*.tmdl' -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = [System.IO.Path]::GetRelativePath($modelFolder, $_.FullName).Replace('\', '/')
    $modelHashes[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$result = [ordered]@{ tmdl_parsed = $true; tables = $database.Model.Tables.Count; relationships = $database.Model.Relationships.Count; parser = 'Microsoft.AnalysisServices.Tabular.TmdlSerializer (official Microsoft TOM assembly)'; model_files_sha256 = $modelHashes; dax_executed = $false }
$result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ProjectRoot 'docs\evidence\tmdl_validation.json') -Encoding utf8
$result | ConvertTo-Json
