[CmdletBinding()]
param(
    [string]$SearchStatePath = ".state/search.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$state = Get-Content $SearchStatePath -Raw | ConvertFrom-Json
$key = az search admin-key show --resource-group $state.resourceGroup --service-name $state.searchServiceName --query primaryKey -o tsv
if (-not $key) { throw "Could not obtain search admin key." }

$headers = @{
    "api-key" = $key
    "Content-Type" = "application/json"
}

$targets = @(
    @{
        indexName = "semiconductor-20260915214135-knowledge-chunks"
        skillsetName = "semiconductor-20260915214135-chunking-skillset"
        dataSourceName = "semiconductor-20260915214135-sharepoint-datasource"
        indexerName = "semiconductor-20260915214135-sharepoint-indexer"
    },
    @{
        indexName = "trustedhr-knowledge-chunks"
        skillsetName = "trustedhr-chunking-skillset"
        dataSourceName = "trustedhr-sharepoint-datasource"
        indexerName = "trustedhr-sharepoint-indexer"
    },
    @{
        indexName = "trustedmfg-knowledge-chunks"
        skillsetName = "trustedmfg-chunking-skillset"
        dataSourceName = "trustedmfg-sharepoint-datasource"
        indexerName = "trustedmfg-sharepoint-indexer"
    },
    @{
        indexName = "trustedsales-knowledge-chunks"
        skillsetName = "trustedsales-chunking-skillset"
        dataSourceName = "trustedsales-sharepoint-datasource"
        indexerName = "trustedsales-sharepoint-indexer"
    }
)

foreach ($t in $targets) {
    Write-Host "`n=== Updating $($t.indexName) ===" -ForegroundColor Cyan
    
    # 1. Update Index with document_iteration field if missing
    try {
        $index = Invoke-RestMethod -Method GET -Uri "$($state.searchEndpoint)/indexes/$($t.indexName)?api-version=$($state.apiVersion)" -Headers $headers
        $hasDocIterField = @($index.fields | Where-Object { $_.name -eq 'document_iteration' }).Count -gt 0
        if (-not $hasDocIterField) {
            Write-Host "  Adding document_iteration field to index..." -ForegroundColor Yellow
            $docIterField = @{
                name = "document_iteration"
                type = "Edm.String"
                searchable = $true
                filterable = $true
                facetable = $true
                retrievable = $true
                sortable = $false
            }
            $index.fields += $docIterField
            $updateIndexBody = $index | ConvertTo-Json -Depth 50
            Invoke-RestMethod -Method PUT -Uri "$($state.searchEndpoint)/indexes/$($t.indexName)?api-version=$($state.apiVersion)" -Headers $headers -Body $updateIndexBody | Out-Null
            Write-Host "  [OK] Index updated with document_iteration field." -ForegroundColor Green
        } else {
            Write-Host "  [OK] document_iteration field already in index." -ForegroundColor Green
        }
    } catch {
        Write-Host "  Error updating index $($t.indexName): $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message -ForegroundColor Red }
    }

    # 2. Update Skillset indexProjections if missing document_iteration mapping
    try {
        $skillset = Invoke-RestMethod -Method GET -Uri "$($state.searchEndpoint)/skillsets/$($t.skillsetName)?api-version=$($state.apiVersion)" -Headers $headers
        if ($skillset.indexProjections -and $skillset.indexProjections.selectors) {
            $selector = $skillset.indexProjections.selectors[0]
            $hasMapping = @($selector.mappings | Where-Object { $_.name -eq 'document_iteration' }).Count -gt 0
            if (-not $hasMapping) {
                Write-Host "  Adding document_iteration mapping to skillset..." -ForegroundColor Yellow
                $selector.mappings += @{
                    name = 'document_iteration'
                    source = '/document/DocumentIteration'
                }
                $updateSkillsetBody = $skillset | ConvertTo-Json -Depth 50
                Invoke-RestMethod -Method PUT -Uri "$($state.searchEndpoint)/skillsets/$($t.skillsetName)?api-version=$($state.apiVersion)" -Headers $headers -Body $updateSkillsetBody | Out-Null
                Write-Host "  [OK] Skillset updated with document_iteration mapping." -ForegroundColor Green
            } else {
                Write-Host "  [OK] Skillset already has document_iteration mapping." -ForegroundColor Green
            }
        }
    } catch {
        Write-Host "  Error updating skillset $($t.skillsetName): $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message -ForegroundColor Red }
    }

    # 3. Update Datasource container query to include DocumentIteration in additionalColumns
    try {
        $ds = Invoke-RestMethod -Method GET -Uri "$($state.searchEndpoint)/datasources/$($t.dataSourceName)?api-version=$($state.apiVersion)" -Headers $headers
        $query = $ds.container.query
        if ($query -notmatch 'DocumentIteration') {
            Write-Host "  Updating datasource query to include DocumentIteration..." -ForegroundColor Yellow
            $newQuery = $query -replace 'additionalColumns=', 'additionalColumns=DocumentIteration,'
            if ($newQuery -eq $query) {
                $newQuery = "$query;additionalColumns=DocumentIteration"
            }
            $ds.container.query = $newQuery
            $updateDsBody = $ds | ConvertTo-Json -Depth 50
            Invoke-RestMethod -Method PUT -Uri "$($state.searchEndpoint)/datasources/$($t.dataSourceName)?api-version=$($state.apiVersion)" -Headers $headers -Body $updateDsBody | Out-Null
            Write-Host "  [OK] Datasource query updated: $newQuery" -ForegroundColor Green
        } else {
            Write-Host "  [OK] Datasource already includes DocumentIteration." -ForegroundColor Green
        }
    } catch {
        Write-Host "  Error updating datasource $($t.dataSourceName): $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message -ForegroundColor Red }
    }

    # 4. Reset & Run Indexer
    try {
        $indexerStatus = Invoke-RestMethod -Method GET -Uri "$($state.searchEndpoint)/indexers/$($t.indexerName)/status?api-version=$($state.apiVersion)" -Headers $headers
        Write-Host "  Current indexer status: $($indexerStatus.status)"
        
        # If running, wait up to 60s
        $waitCount = 0
        while ($indexerStatus.status -eq 'running' -and $waitCount -lt 6) {
            Write-Host "  Indexer is currently running, waiting 10s..."
            Start-Sleep -Seconds 10
            $indexerStatus = Invoke-RestMethod -Method GET -Uri "$($state.searchEndpoint)/indexers/$($t.indexerName)/status?api-version=$($state.apiVersion)" -Headers $headers
            $waitCount++
        }

        Write-Host "  Resetting indexer $($t.indexerName)..." -ForegroundColor Yellow
        try {
            Invoke-RestMethod -Method POST -Uri "$($state.searchEndpoint)/indexers/$($t.indexerName)/reset?api-version=$($state.apiVersion)" -Headers $headers | Out-Null
        } catch {
            Write-Host "  Reset warning: $($_.Exception.Message)"
        }
        
        Start-Sleep -Seconds 2
        Write-Host "  Running indexer $($t.indexerName)..." -ForegroundColor Yellow
        Invoke-RestMethod -Method POST -Uri "$($state.searchEndpoint)/indexers/$($t.indexerName)/run?api-version=$($state.apiVersion)" -Headers $headers | Out-Null
        Write-Host "  [OK] Indexer reset and run triggered successfully." -ForegroundColor Green
    } catch {
        Write-Host "  Error running indexer $($t.indexerName): $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "`nAll search indexers have been updated and execution triggered." -ForegroundColor Green
