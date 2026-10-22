// Create a blank query named GoldTable; store credentials in Power BI, never here.
// Usage in another query: GoldTable("risk_metrics_current")
(TableName as text) as table =>
let
    Source = DatabricksMultiCloud.Catalogs(
        "dbc-236f6036-39b4.cloud.databricks.com",
        "/sql/1.0/warehouses/e4f1304cb2d303ea",
        [Catalog="workspace", Database="jet_fuel_gold", EnableAutomaticProxyDiscovery=null]),
    // Catalog + Database scope the connector to a flat, qualified-name navigator.
    QualifiedName = "workspace.jet_fuel_gold." & TableName,
    Matches = Table.SelectRows(Source, each Text.Remove(Text.From([Name]), {"`", "'", """"}) = QualifiedName),
    Result = if Table.RowCount(Matches) <> 1 then error "Gold table/view not found uniquely" else Matches{0}[Data]
in
    Result
