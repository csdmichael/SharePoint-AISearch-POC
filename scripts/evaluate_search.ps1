[CmdletBinding()]
param(
    [string]$CasesPath = (Join-Path $PSScriptRoot '..\config\search-evaluation.cases'),
    [string]$SearchStatePath = (Join-Path $PSScriptRoot '..\.state\search.json'),
    [string]$SharePointStatePath = (Join-Path $PSScriptRoot '..\.state\sharepoint.json'),
    [string]$ReportPath = (Join-Path $PSScriptRoot '..\.state\search-evaluation.json'),
    [ValidateRange(3, 50)][int]$Top = 5,
    [ValidateRange(0, 1)][double]$MinimumSourceHitAt3 = 0.9
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-PlainToken {
    param([Parameter(Mandatory)][object]$TokenResult)
    if ($TokenResult.Token -is [Security.SecureString]) {
        return [Net.NetworkCredential]::new('', $TokenResult.Token).Password
    }
    return [string]$TokenResult.Token
}

function Find-Rank {
    param(
        [Parameter(Mandatory)][object[]]$Results,
        [Parameter(Mandatory)][string]$Field,
        [Parameter(Mandatory)][string]$Expected
    )
    for ($index = 0; $index -lt $Results.Count; $index++) {
        if ([string]$Results[$index].$Field -eq $Expected) { return $index + 1 }
    }
    return $null
}

foreach ($requiredPath in @($CasesPath, $SearchStatePath, $SharePointStatePath)) {
    if (-not (Test-Path $requiredPath)) { throw "Required file not found: $requiredPath" }
}
$cases = @(Get-Content $CasesPath -Raw | ConvertFrom-Json)
if (-not $cases.Count) { throw 'The evaluation set is empty.' }
$state = Get-Content $SearchStatePath -Raw | ConvertFrom-Json
$sharePoint = Get-Content $SharePointStatePath -Raw | ConvertFrom-Json

$armToken = Get-PlainToken (Get-AzAccessToken -ResourceUrl 'https://management.azure.com' -TenantId $sharePoint.tenantId)
$resourcePath = "/subscriptions/$($state.subscriptionId)/resourceGroups/$($state.resourceGroup)/providers/Microsoft.Search/searchServices/$($state.searchServiceName)"
$keys = Invoke-RestMethod -Method POST -Headers @{ Authorization = "Bearer $armToken" } -Uri "https://management.azure.com$resourcePath/listAdminKeys?api-version=2025-05-01"
$headers = @{ 'api-key' = $keys.primaryKey; 'Content-Type' = 'application/json' }
$searchUri = "$($state.searchEndpoint)/indexes/$($state.indexName)/docs/search?api-version=$($state.apiVersion)"

$evaluations = @()
foreach ($case in $cases) {
    $body = @{
        search = $case.query
        count = $true
        top = $Top
        queryType = 'semantic'
        semanticConfiguration = 'semiconductor-semantic-config'
        select = 'chunk_id,parent_id,title,document_url,category,source_table'
        vectorQueries = @(
            @{
                kind = 'text'
                text = $case.query
                fields = 'chunk_vector'
                k = [Math]::Max(20, $Top)
            }
        )
    }
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-RestMethod -Method POST -Headers $headers -Uri $searchUri -Body ($body | ConvertTo-Json -Depth 10)
    $timer.Stop()
    $results = @($response.value)
    $categoryRank = Find-Rank -Results $results -Field 'category' -Expected $case.expectedCategory
    $sourceRank = Find-Rank -Results $results -Field 'source_table' -Expected $case.expectedSourceTable
    $evaluations += [ordered]@{
        id = $case.id
        query = $case.query
        expectedCategory = $case.expectedCategory
        expectedSourceTable = $case.expectedSourceTable
        categoryRank = $categoryRank
        sourceTableRank = $sourceRank
        latencyMs = $timer.ElapsedMilliseconds
        results = @(
            $results | ForEach-Object {
                [ordered]@{
                    title = $_.title
                    category = $_.category
                    sourceTable = $_.source_table
                    chunkId = $_.chunk_id
                    parentId = $_.parent_id
                    documentUrl = $_.document_url
                    score = $_.'@search.score'
                    rerankerScore = $_.'@search.rerankerScore'
                }
            }
        )
    }
}

$caseCount = $evaluations.Count
$sourceAt1 = @($evaluations | Where-Object sourceTableRank -eq 1).Count / $caseCount
$sourceAt3 = @($evaluations | Where-Object { $_.sourceTableRank -and $_.sourceTableRank -le 3 }).Count / $caseCount
$categoryAt1 = @($evaluations | Where-Object categoryRank -eq 1).Count / $caseCount
$reciprocalRanks = @($evaluations | ForEach-Object { if ($_.sourceTableRank) { 1.0 / $_.sourceTableRank } else { 0.0 } })
$latencies = @($evaluations.latencyMs | Sort-Object)
$p95Index = [Math]::Max(0, [Math]::Ceiling($latencies.Count * 0.95) - 1)

$feedbackSummary = @{ available = $false; documents = 0; relevant = 0; notRelevant = 0 }
if ($state.PSObject.Properties.Name -contains 'feedbackIndexName') {
    $feedbackUri = "$($state.searchEndpoint)/indexes/$($state.feedbackIndexName)/docs/search?api-version=$($state.apiVersion)"
    try {
        $generation = $state.indexName.Replace("'", "''")
        $feedback = Invoke-RestMethod -Method POST -Headers $headers -Uri $feedbackUri -Body (@{
            search = '*'
            count = $true
            top = 0
            filter = "deployment_generation eq '$generation'"
            facets = @('relevant,count:2')
        } | ConvertTo-Json -Depth 5)
        $feedbackSummary.available = $true
        $feedbackSummary.documents = $feedback.'@odata.count'
        foreach ($facet in @($feedback.'@search.facets'.relevant)) {
            if ($facet.value) { $feedbackSummary.relevant = $facet.count }
            else { $feedbackSummary.notRelevant = $facet.count }
        }
    }
    catch {
        throw "Feedback index query failed: $($_.Exception.Message)"
    }
}

$report = [ordered]@{
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    indexName = $state.indexName
    chunkSize = if ($state.PSObject.Properties.Name -contains 'chunkSize') { $state.chunkSize } else { 512 }
    chunkOverlap = if ($state.PSObject.Properties.Name -contains 'chunkOverlap') { $state.chunkOverlap } else { 128 }
    top = $Top
    metrics = [ordered]@{
        caseCount = $caseCount
        categoryRoutingAt1 = [Math]::Round($categoryAt1, 4)
        sourceTableRoutingAt1 = [Math]::Round($sourceAt1, 4)
        sourceTableRoutingAt3 = [Math]::Round($sourceAt3, 4)
        sourceTableRoutingMrr = [Math]::Round(($reciprocalRanks | Measure-Object -Average).Average, 4)
        averageLatencyMs = [Math]::Round(($latencies | Measure-Object -Average).Average, 1)
        p95LatencyMs = $latencies[$p95Index]
    }
    feedback = $feedbackSummary
    cases = $evaluations
}
$directory = Split-Path $ReportPath -Parent
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$report | ConvertTo-Json -Depth 20 | Set-Content -Path $ReportPath -Encoding utf8
$report | ConvertTo-Json -Depth 8

if ($sourceAt3 -lt $MinimumSourceHitAt3) {
    throw "Source-table routing@3 $([Math]::Round($sourceAt3, 4)) is below threshold $MinimumSourceHitAt3."
}

Remove-Variable armToken,keys