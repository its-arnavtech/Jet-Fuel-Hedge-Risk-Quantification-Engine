param(
    [Parameter(Mandatory=$true)][string]$PortFile,
    [Parameter(Mandatory=$true)][string]$DatabaseId,
    [Parameter(Mandatory=$true)][string]$AssemblyFolder,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = 'Stop'
foreach ($assembly in @('Microsoft.AnalysisServices.Core.dll','Microsoft.AnalysisServices.Tabular.dll')) {
    [void][Reflection.Assembly]::LoadFrom((Join-Path (Resolve-Path -LiteralPath $AssemblyFolder).Path $assembly))
}
$localModelPort = (Get-Content -LiteralPath $PortFile -Raw) -replace '\D',''
if ($localModelPort -notmatch '^\d{1,5}$') { throw 'Invalid Desktop port' }
$definitionFolder = Join-Path $ProjectRoot 'powerbi\JetFuelHedgeRisk\JetFuelHedgeRisk.SemanticModel\definition'
$sourceDatabase = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeDatabaseFromFolder($definitionFolder)
$localServer = [Microsoft.AnalysisServices.Tabular.Server]::new()
$localServer.Connect("Data Source=localhost:$localModelPort")
try {
    $targetDatabase = $localServer.Databases.FindByName($DatabaseId)
    if ($null -eq $targetDatabase) { $targetDatabase = $localServer.Databases.Find($DatabaseId) }
    if ($null -eq $targetDatabase) { throw 'Expected the open JetFuelHedgeRisk model' }
    # Desktop may add hidden auto-date tables during Import. Verify every project
    # table by name without editing those Desktop-managed tables.
    foreach ($sourceTable in $sourceDatabase.Model.Tables) {
        if ($null -eq $targetDatabase.Model.Tables.Find($sourceTable.Name)) { throw 'Open model is missing a project table' }
    }
    # Metadata only. Never read or replace data sources/credentials, submit processing,
    # or modify report files. Desktop must perform the subsequent Import refresh.
    $targetDatabase.Model.Expressions['GoldTable'].Expression = $sourceDatabase.Model.Expressions['GoldTable'].Expression
    foreach ($sourceMeasure in $sourceDatabase.Model.Tables['_Measures'].Measures) {
        $targetMeasure = $targetDatabase.Model.Tables['_Measures'].Measures.Find($sourceMeasure.Name)
        if ($null -eq $targetMeasure) {
            $targetDatabase.Model.Tables['_Measures'].Measures.Add($sourceMeasure.Clone())
        } else {
            $targetMeasure.Expression = $sourceMeasure.Expression
            $targetMeasure.FormatString = $sourceMeasure.FormatString
            $targetMeasure.DisplayFolder = $sourceMeasure.DisplayFolder
            $targetMeasure.Description = $sourceMeasure.Description
        }
    }
    $targetDatabase.Model.Tables['Market Steps'].Partitions[0].Source.Expression = $sourceDatabase.Model.Tables['Market Steps'].Partitions[0].Source.Expression
    [void]$targetDatabase.Model.SaveChanges()
    [ordered]@{metadata_synced=$true;measure_count=$targetDatabase.Model.Tables['_Measures'].Measures.Count;import_refreshed=$false;method='Official Microsoft TOM metadata API';checked_at=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json
} finally {
    $localServer.Disconnect()
}
