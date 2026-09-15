[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SearchStatePath,
    [Parameter(Mandatory)][bool]$Disabled,
    [string]$SharePointStatePath = (Join-Path $PSScriptRoot '..\.state\sharepoint.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $SearchStatePath)) { throw "Search state not found: $SearchStatePath" }
if (-not (Test-Path $SharePointStatePath)) { throw "SharePoint state not found: $SharePointStatePath" }
$state = Get-Content $SearchStatePath -Raw | ConvertFrom-Json
$sharePoint = Get-Content $SharePointStatePath -Raw | ConvertFrom-Json
$tokenResult = Get-AzAccessToken -ResourceUrl 'https://management.azure.com' -TenantId $sharePoint.tenantId
$armToken = if ($tokenResult.Token -is [Security.SecureString]) {
    [Net.NetworkCredential]::new('', $tokenResult.Token).Password
} else { [string]$tokenResult.Token }
$resourcePath = "/subscriptions/$($state.subscriptionId)/resourceGroups/$($state.resourceGroup)/providers/Microsoft.Search/searchServices/$($state.searchServiceName)"
$keys = Invoke-RestMethod -Method POST -Headers @{ Authorization = "Bearer $armToken" } -Uri "https://management.azure.com$resourcePath/listAdminKeys?api-version=2025-05-01"
$headers = @{ 'api-key' = $keys.primaryKey; 'Content-Type' = 'application/json' }
$uri = "$($state.searchEndpoint)/indexers/$($state.indexerName)?api-version=$($state.apiVersion)"
$indexer = Invoke-RestMethod -Method GET -Headers $headers -Uri $uri
$indexer.disabled = $Disabled
Invoke-RestMethod -Method PUT -Headers $headers -Uri $uri -Body ($indexer | ConvertTo-Json -Depth 30) | Out-Null
$verified = Invoke-RestMethod -Method GET -Headers $headers -Uri $uri
if ([bool]$verified.disabled -ne $Disabled) {
    throw "Indexer $($state.indexerName) disabled state did not converge to $Disabled."
}
[pscustomobject]@{
    indexerName = $state.indexerName
    targetIndexName = $state.indexName
    disabled = [bool]$verified.disabled
} | ConvertTo-Json

Remove-Variable armToken,tokenResult,keys