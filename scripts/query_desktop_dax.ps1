param(
    [Parameter(Mandatory=$true)][string]$PortFile,
    [Parameter(Mandatory=$true)][string]$DatabaseId,
    [Parameter(Mandatory=$true)][string]$AssemblyFolder,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = 'Stop'
$clientAssembly = Join-Path (Resolve-Path -LiteralPath $AssemblyFolder).Path 'Microsoft.AnalysisServices.AdomdClient.dll'
[void][System.Reflection.Assembly]::LoadFrom($clientAssembly)
# Desktop's local port file may be UTF-16 without a BOM. Read digits only, never credential stores.
$localModelPort = (Get-Content -LiteralPath $PortFile -Raw) -replace '\D',''
if ($localModelPort -notmatch '^\d{1,5}$') { throw 'Invalid local Analysis Services port' }
$connection = [Microsoft.AnalysisServices.AdomdClient.AdomdConnection]::new("Data Source=localhost:$localModelPort;Initial Catalog=$DatabaseId")
$connection.Open()
function Invoke-LocalDax([string]$Statement) {
    $command = $connection.CreateCommand()
    $command.CommandText = $Statement
    $command.CommandTimeout = 120
    $reader = $command.ExecuteReader()
    $rows = [System.Collections.Generic.List[object]]::new()
    while ($reader.Read()) {
        $row = [ordered]@{}
        for ($column = 0; $column -lt $reader.FieldCount; $column++) {
            $name = $reader.GetName($column)
            if ($name -match '\[([^\]]+)\]$') { $name = $Matches[1] }
            $row[$name] = if ($reader.IsDBNull($column)) { $null } else { $reader.GetValue($column) }
        }
        $rows.Add($row)
    }
    $reader.Close()
    return ,$rows.ToArray()
}
try {
    $status = Invoke-LocalDax 'EVALUATE ROW("Readiness",[Readiness],"Header",[Header])'
    $headlines = Invoke-LocalDax (Get-Content -LiteralPath (Join-Path $ProjectRoot 'powerbi\tests\headlines.dax') -Raw -Encoding utf8)
    $numbers = Invoke-LocalDax (Get-Content -LiteralPath (Join-Path $ProjectRoot 'powerbi\tests\headline_numbers.dax') -Raw -Encoding utf8)
    $grainSource = Get-Content -LiteralPath (Join-Path $ProjectRoot 'powerbi\tests\grains.dax') -Raw -Encoding utf8
    $grainStatements = [regex]::Split($grainSource, '(?m)(?=^EVALUATE )') | Where-Object { $_ -match '^EVALUATE ' }
    $grains = @($grainStatements | ForEach-Object { ,(Invoke-LocalDax $_) })
    $multiScenario = Invoke-LocalDax 'EVALUATE CALCULATETABLE(ROW("Savings",[Route Savings M],"Cost",[Fuel Cost USD]),TREATAS({"H000","H080"},''Hedge Scenario''[scenario_id]))'
    $result = [ordered]@{dax_executed=$true; ready=($status[0]['Readiness'] -eq 'Ready'); status=$status; headlines=$headlines; numbers=$numbers; grains=$grains; multiple_scenarios=$multiScenario; source='Read-only ADOMD query of open Power BI Desktop model'; checked_at=[DateTime]::UtcNow.ToString('o')}
    $output = Join-Path $ProjectRoot 'docs\evidence\powerbi_dax_results.json'
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $output -Encoding utf8
    [ordered]@{dax_executed=$true;ready=$result.ready;headlines=$headlines;status=$status} | ConvertTo-Json -Depth 5
} finally {
    $connection.Close()
}
