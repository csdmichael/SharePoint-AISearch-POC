[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\deployment.json'),
    [string]$AliasName,
    [string]$CandidateSearchStatePath,
    [string]$CurrentSearchStatePath,
    [string]$SharePointStatePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment_config.ps1')
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$config = Import-DeploymentConfig -Path $ConfigPath
function Get-ConfigValue {
    param([Parameter(Mandatory)][string]$Path)
    return Get-DeploymentConfigValue -Config $config -Path $Path
}
if (-not $PSBoundParameters.ContainsKey('AliasName')) { $AliasName = Get-ConfigValue 'search.indexAliasName' }
foreach ($binding in @(
    @{ Name = 'CandidateSearchStatePath'; Config = 'paths.candidateSearchState' },
    @{ Name = 'CurrentSearchStatePath'; Config = 'paths.searchState' },
    @{ Name = 'SharePointStatePath'; Config = 'paths.sharePointState' }
)) {
    if (-not $PSBoundParameters.ContainsKey($binding.Name)) {
        Set-Variable -Name $binding.Name -Value (Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue $binding.Config))
    }
}
$SearchManagementApiVersion = Get-ConfigValue 'apiVersions.searchManagement'
$ManagedPrefix = Get-ConfigValue 'search.resourceNamePrefix'
$IndexerNameSuffix = Get-ConfigValue 'search.indexerNameSuffix'
$IndexNameSuffix = Get-ConfigValue 'search.indexNameSuffix'

foreach ($requiredPath in @($CandidateSearchStatePath, $SharePointStatePath)) {
    if (-not (Test-Path $requiredPath)) { throw "Required state file not found: $requiredPath" }
}
$candidate = Get-Content $CandidateSearchStatePath -Raw | ConvertFrom-Json
$sharePoint = Get-Content $SharePointStatePath -Raw | ConvertFrom-Json
$tokenResult = Get-AzAccessToken -ResourceUrl 'https://management.azure.com' -TenantId $sharePoint.tenantId
$armToken = if ($tokenResult.Token -is [Security.SecureString]) {
    [Net.NetworkCredential]::new('', $tokenResult.Token).Password
} else { [string]$tokenResult.Token }
$resourcePath = "/subscriptions/$($candidate.subscriptionId)/resourceGroups/$($candidate.resourceGroup)/providers/Microsoft.Search/searchServices/$($candidate.searchServiceName)"
$keys = Invoke-RestMethod -Method POST -Headers @{ Authorization = "Bearer $armToken" } -Uri "https://management.azure.com$resourcePath/listAdminKeys?api-version=$SearchManagementApiVersion"
$headers = @{ 'api-key' = $keys.primaryKey; 'Content-Type' = 'application/json' }
$aliasUri = "$($candidate.searchEndpoint)/aliases/$AliasName`?api-version=$($candidate.apiVersion)"
$body = @{ name = $AliasName; indexes = @($candidate.indexName) }
Invoke-RestMethod -Method PUT -Headers $headers -Uri $aliasUri -Body ($body | ConvertTo-Json -Depth 5) | Out-Null
$alias = Invoke-RestMethod -Method GET -Headers $headers -Uri $aliasUri
if (@($alias.indexes).Count -ne 1 -or $alias.indexes[0] -ne $candidate.indexName) {
    throw "Alias $AliasName was not promoted to $($candidate.indexName)."
}

$indexers = Invoke-RestMethod -Method GET -Headers $headers -Uri "$($candidate.searchEndpoint)/indexers?api-version=$($candidate.apiVersion)"
$disabledRollbackIndexers = @()
foreach ($indexer in @($indexers.value)) {
    $isManagedIndexer = $indexer.name -like "$ManagedPrefix*-$IndexerNameSuffix" -and
        $indexer.targetIndexName -like "$ManagedPrefix*-$IndexNameSuffix"
    if (-not $isManagedIndexer) { continue }
    $shouldDisable = $indexer.name -ne $candidate.indexerName
    if ([bool]$indexer.disabled -ne $shouldDisable) {
        $indexer.disabled = $shouldDisable
        $indexerUri = "$($candidate.searchEndpoint)/indexers/$($indexer.name)?api-version=$($candidate.apiVersion)"
        Invoke-RestMethod -Method PUT -Headers $headers -Uri $indexerUri -Body ($indexer | ConvertTo-Json -Depth 30) | Out-Null
    }
    if ($shouldDisable) { $disabledRollbackIndexers += $indexer.name }
}
$promotedIndexer = Invoke-RestMethod -Method GET -Headers $headers -Uri "$($candidate.searchEndpoint)/indexers/$($candidate.indexerName)?api-version=$($candidate.apiVersion)"
if ($promotedIndexer.disabled) { throw "Promoted indexer $($candidate.indexerName) is disabled." }

$candidate | Add-Member -NotePropertyName aliasName -NotePropertyValue $AliasName -Force
$candidate | Add-Member -NotePropertyName promotedAt -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o') -Force
$currentDirectory = Split-Path $CurrentSearchStatePath -Parent
New-Item -ItemType Directory -Path $currentDirectory -Force | Out-Null
$candidate | ConvertTo-Json -Depth 8 | Set-Content -Path $CurrentSearchStatePath -Encoding utf8

[pscustomobject]@{
    aliasName = $AliasName
    indexName = $candidate.indexName
    previousIndexRetained = $true
    disabledRollbackIndexers = $disabledRollbackIndexers
    currentSearchStatePath = $CurrentSearchStatePath
} | ConvertTo-Json

Remove-Variable armToken,tokenResult,keys