[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Query,
    [Parameter(Mandatory)][string]$ChunkId,
    [Parameter(Mandatory)][string]$ParentId,
    [Parameter(Mandatory)][string]$DocumentUrl,
    [Parameter(Mandatory)][string]$Category,
    [Parameter(Mandatory)][string]$SourceTable,
    [Parameter(Mandatory)][ValidateRange(1, 5)][int]$Rating,
    [Parameter(Mandatory)][bool]$Relevant,
    [string]$Comment = '',
    [string]$SearchStatePath = (Join-Path $PSScriptRoot '..\.state\search.json'),
    [string]$SharePointStatePath = (Join-Path $PSScriptRoot '..\.state\sharepoint.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $SearchStatePath)) { throw "Search state not found: $SearchStatePath" }
if (-not (Test-Path $SharePointStatePath)) { throw "SharePoint state not found: $SharePointStatePath" }
$state = Get-Content $SearchStatePath -Raw | ConvertFrom-Json
$sharePoint = Get-Content $SharePointStatePath -Raw | ConvertFrom-Json
if (-not ($state.PSObject.Properties.Name -contains 'feedbackIndexName')) {
    throw 'The Search deployment does not include a feedback index. Rerun provision_search.ps1.'
}

$tokenResult = Get-AzAccessToken -ResourceUrl 'https://management.azure.com' -TenantId $sharePoint.tenantId
$armToken = if ($tokenResult.Token -is [Security.SecureString]) {
    [Net.NetworkCredential]::new('', $tokenResult.Token).Password
} else { [string]$tokenResult.Token }
$resourcePath = "/subscriptions/$($state.subscriptionId)/resourceGroups/$($state.resourceGroup)/providers/Microsoft.Search/searchServices/$($state.searchServiceName)"
$keys = Invoke-RestMethod -Method POST -Headers @{ Authorization = "Bearer $armToken" } -Uri "https://management.azure.com$resourcePath/listAdminKeys?api-version=2025-05-01"
$feedbackId = [Guid]::NewGuid().ToString('N')
$feedbackTimestamp = (Get-Date).ToUniversalTime().ToString('o')
$body = @{
    value = @(
        @{
            '@search.action' = 'upload'
            feedback_id = $feedbackId
            query = $Query
            chunk_id = $ChunkId
            parent_id = $ParentId
            document_url = $DocumentUrl
            category = $Category
            source_table = $SourceTable
            deployment_generation = $state.indexName
            rating = $Rating
            relevant = $Relevant
            comment = $Comment
            retrieved_at = $feedbackTimestamp
            created_at = $feedbackTimestamp
        }
    )
}
$uri = "$($state.searchEndpoint)/indexes/$($state.feedbackIndexName)/docs/index?api-version=$($state.apiVersion)"
$response = Invoke-RestMethod -Method POST -Headers @{ 'api-key' = $keys.primaryKey; 'Content-Type' = 'application/json' } -Uri $uri -Body ($body | ConvertTo-Json -Depth 10)
$result = $response.value[0]
if (-not $result.status) {
    throw "Feedback write failed ($($result.statusCode)): $($result.errorMessage)"
}
[pscustomobject]@{
    feedbackId = $feedbackId
    succeeded = $result.status
    statusCode = $result.statusCode
    feedbackIndex = $state.feedbackIndexName
    deploymentGeneration = $state.indexName
} | ConvertTo-Json

Remove-Variable armToken,tokenResult,keys