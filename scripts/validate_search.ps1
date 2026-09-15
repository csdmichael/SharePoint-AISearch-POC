[CmdletBinding()]
param(
    [string]$ResourceGroup = 'm365-myaacoub',
    [string]$SearchStatePath = (Join-Path $PSScriptRoot '..\.state\search.json'),
    [string]$SharePointStatePath = (Join-Path $PSScriptRoot '..\.state\sharepoint.json'),
    [string]$ManifestPath = (Join-Path $PSScriptRoot '..\corpus\manifest.json'),
    [int]$ExpectedDocuments = 100,
    [int]$WaitMinutes = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $SearchStatePath)) { throw "Search state not found at $SearchStatePath." }
if (-not (Test-Path $SharePointStatePath)) { throw "SharePoint state not found at $SharePointStatePath." }
if (-not (Test-Path $ManifestPath)) { throw "Corpus manifest not found at $ManifestPath." }
$state = Get-Content $SearchStatePath -Raw | ConvertFrom-Json
$sharePoint = Get-Content $SharePointStatePath -Raw | ConvertFrom-Json
$manifest = @(Get-Content $ManifestPath -Raw | ConvertFrom-Json)
if ($manifest.Count -ne $ExpectedDocuments) {
    throw "Expected $ExpectedDocuments manifest entries, found $($manifest.Count)."
}
$tokenResult = Get-AzAccessToken -ResourceUrl 'https://management.azure.com' -TenantId $sharePoint.tenantId
$armToken = if ($tokenResult.Token -is [Security.SecureString]) {
    [Net.NetworkCredential]::new('', $tokenResult.Token).Password
} else { [string]$tokenResult.Token }
$searchResourcePath = "/subscriptions/$($state.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.Search/searchServices/$($state.searchServiceName)"
$keysUri = "https://management.azure.com$searchResourcePath/listAdminKeys?api-version=2025-05-01"
$keys = Invoke-RestMethod -Method POST -Headers @{ Authorization = "Bearer $armToken" } -Uri $keysUri
$adminKey = $keys.primaryKey
if (-not $adminKey) { throw 'Could not obtain an ephemeral Search admin key.' }
$headers = @{ 'api-key' = $adminKey; 'Content-Type' = 'application/json' }
$baseUri = $state.searchEndpoint
$apiVersion = $state.apiVersion
$minimumStartTime = if ($state.PSObject.Properties.Name -contains 'indexerTriggeredAt') {
    [DateTimeOffset]::Parse($state.indexerTriggeredAt).AddSeconds(-5)
} else { [DateTimeOffset]::MinValue }

$deadline = [DateTimeOffset]::UtcNow.AddMinutes($WaitMinutes)
do {
    $status = Invoke-RestMethod -Method GET -Headers $headers -Uri "$baseUri/indexers/$($state.indexerName)/status?api-version=$apiVersion"
    $lastResult = $status.lastResult
    if (-not $lastResult -and $status.executionHistory.Count) { $lastResult = $status.executionHistory[0] }
    $resultStartTime = if ($lastResult -and $lastResult.startTime) {
        [DateTimeOffset]::Parse($lastResult.startTime)
    } else { [DateTimeOffset]::MinValue }
    $running = -not $lastResult -or $lastResult.status -eq 'inProgress' -or $resultStartTime -lt $minimumStartTime
    if ($running -and [DateTimeOffset]::UtcNow -lt $deadline) {
        Write-Host 'Waiting for SharePoint indexer completion...'
        [Threading.Thread]::Sleep(10000)
    }
} while ($running -and [DateTimeOffset]::UtcNow -lt $deadline)
if ($running) { throw "Indexer did not complete within $WaitMinutes minutes." }
$executionQuiescent = $lastResult.status -ne 'inProgress' -and $null -ne $lastResult.endTime

$coverageQuery = @{
    search = '*'
    count = $true
    top = 0
    facets = @(
        'parent_id,count:1000',
        'artifact_id,count:1000',
        'file_extension,count:10',
        'category,count:10'
    )
}
$coverage = Invoke-RestMethod -Method POST -Headers $headers -Uri "$baseUri/indexes/$($state.indexName)/docs/search?api-version=$apiVersion" -Body ($coverageQuery | ConvertTo-Json -Depth 10)
$inventoryQuery = @{
    search = '*'
    count = $true
    top = 1000
    select = 'parent_id,title,document_url,document_path,file_extension,artifact_id,category,source_table,source_system,profile_generated_at'
}
$inventory = Invoke-RestMethod -Method POST -Headers $headers -Uri "$baseUri/indexes/$($state.indexName)/docs/search?api-version=$apiVersion" -Body ($inventoryQuery | ConvertTo-Json -Depth 10)
if ($inventory.'@odata.count' -gt 1000) { throw 'Search inventory exceeds the validator paging limit of 1000 chunks.' }
$missingLineageQuery = @{
    search = '*'
    count = $true
    top = 0
    filter = 'artifact_id eq null or category eq null or source_table eq null or document_url eq null or profile_generated_at eq null'
}
$missingLineage = Invoke-RestMethod -Method POST -Headers $headers -Uri "$baseUri/indexes/$($state.indexName)/docs/search?api-version=$apiVersion" -Body ($missingLineageQuery | ConvertTo-Json -Depth 10)

$query = @{
    search = 'AI accelerator wafer yield defects production risk'
    count = $true
    top = 5
    queryType = 'semantic'
    semanticConfiguration = 'semiconductor-semantic-config'
    select = 'parent_id,title,chunk,document_url,file_extension,artifact_id,category,source_table'
    vectorQueries = @(
        @{
            kind = 'text'
            text = 'AI accelerator wafer yield defects production risk'
            fields = 'chunk_vector'
            k = 5
        }
    )
}
$result = Invoke-RestMethod -Method POST -Headers $headers -Uri "$baseUri/indexes/$($state.indexName)/docs/search?api-version=$apiVersion" -Body ($query | ConvertTo-Json -Depth 10)
$parentCount = @($coverage.'@search.facets'.parent_id).Count
$artifactCount = @($coverage.'@search.facets'.artifact_id).Count
$formats = @($coverage.'@search.facets'.file_extension | ForEach-Object { $_.value })
$categories = @($coverage.'@search.facets'.category | ForEach-Object { $_.value })

$summary = [ordered]@{
    indexerOperationalStatus = $status.status
    executionQuiescent = $executionQuiescent
    lastRunStatus = $lastResult.status
    lastRunStartTime = $lastResult.startTime
    lastRunEndTime = $lastResult.endTime
    itemsProcessed = $lastResult.itemsProcessed
    itemsFailed = $lastResult.itemsFailed
    chunkCount = $coverage.'@odata.count'
    uniqueSourceDocuments = $parentCount
    uniqueArtifacts = $artifactCount
    chunksMissingLineage = $missingLineage.'@odata.count'
    indexedFormats = $formats
    indexedCategories = $categories
    hybridQueryResults = @($result.value).Count
    topResult = if (@($result.value).Count) {
        @{
            title = $result.value[0].title
            category = $result.value[0].category
            sourceTable = $result.value[0].source_table
            documentUrl = $result.value[0].document_url
            semanticScore = $result.value[0].'@search.rerankerScore'
        }
    } else { $null }
    sharePointUrl = $sharePoint.siteUrl
    libraryUrl = $sharePoint.libraryUrl
    searchEndpoint = $state.searchEndpoint
}
$summary | ConvertTo-Json -Depth 8

if (-not $executionQuiescent) { throw 'Indexer execution is not quiescent.' }
if ($lastResult.status -ne 'success') { throw "Indexer last run status is $($lastResult.status)." }
if ($lastResult.itemsFailed -ne 0) { throw "Indexer reported $($lastResult.itemsFailed) failed items." }
if (@($lastResult.warnings).Count -ne 0) { throw "Indexer reported $(@($lastResult.warnings).Count) warnings." }
if ($parentCount -ne $ExpectedDocuments) {
    throw "Expected $ExpectedDocuments unique source documents, found $parentCount."
}
if ($artifactCount -ne $ExpectedDocuments) {
    throw "Expected $ExpectedDocuments unique artifact IDs, found $artifactCount."
}
$formatDifference = @(Compare-Object @('.docx', '.pptx', '.xlsx') @($formats | Sort-Object))
if ($formatDifference.Count) { throw "Indexed formats are incomplete: $($formats -join ', ')." }
$expectedCategories = @('Inventory', 'Manufacturing', 'Quality', 'Sales', 'Supply Chain', 'Yield')
$categoryDifference = @(Compare-Object $expectedCategories @($categories | Sort-Object))
if ($categoryDifference.Count) { throw "Indexed categories are incomplete: $($categories -join ', ')." }
if ($missingLineage.'@odata.count' -ne 0) {
    throw "$($missingLineage.'@odata.count') chunks are missing lineage or citation fields."
}
$chunksByArtifact = @{}
foreach ($chunk in @($inventory.value)) {
    if (-not $chunksByArtifact.ContainsKey($chunk.artifact_id)) { $chunksByArtifact[$chunk.artifact_id] = @() }
    $chunksByArtifact[$chunk.artifact_id] += $chunk
}
$manifestIds = @($manifest.artifact_id | Sort-Object)
$indexedIds = @($chunksByArtifact.Keys | Sort-Object)
if (@(Compare-Object $manifestIds $indexedIds).Count) {
    throw 'Indexed artifact IDs do not exactly match the corpus manifest.'
}
foreach ($item in $manifest) {
    $chunks = @($chunksByArtifact[$item.artifact_id])
    $parents = @($chunks.parent_id | Sort-Object -Unique)
    if ($parents.Count -ne 1) { throw "Artifact $($item.artifact_id) maps to $($parents.Count) parents." }
    foreach ($chunk in $chunks) {
        $tupleMatches = $chunk.title -eq $item.filename -and
            $chunk.file_extension -eq ".$($item.extension)" -and
            $chunk.category -eq $item.category -and
            $chunk.source_table -eq $item.source_table -and
            $chunk.source_system -eq $item.source_system -and
            $chunk.document_path -like "*$($item.filename)" -and
            $chunk.document_url -like "*$($item.filename)*"
        $expectedTimestamp = [DateTimeOffset]::Parse($item.profile_generated_at)
        $actualTimestamp = [DateTimeOffset]::Parse($chunk.profile_generated_at)
        if (-not $tupleMatches -or [Math]::Abs(($actualTimestamp - $expectedTimestamp).TotalSeconds) -gt 1) {
            throw "Indexed lineage tuple does not match the manifest for $($item.artifact_id)."
        }
    }
}
if (@($result.value).Count -eq 0) { throw 'The hybrid semantic/vector query returned no results.' }

Remove-Variable adminKey
Remove-Variable armToken,tokenResult