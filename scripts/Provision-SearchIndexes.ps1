<#
.SYNOPSIS
    Builds the Azure AI Search layer for the knowledge hubs from config/search-indexes.json and retires superseded objects.

.DESCRIPTION
    For every index in the config this script creates or updates, in dependency order:
      1. the index (chunk fields, vector field with HNSW, semantic configuration and every governance field named in
         config/governance-policy.json, so the Foundry knowledge base can filter on lifecycle, authority, AI readiness
         and sensitivity);
      2. one skillset that splits content into token-aware pages and embeds each page (integrated vectorization),
         then projects one search document per chunk with the SharePoint metadata and governance columns;
      3. one SharePoint datasource per hub site, indexing that hub's document libraries in place;
      4. one indexer per datasource on the configured schedule;
      5. the index alias, and the Foundry IQ knowledge source that reads the index.
    With -Prune it then deletes the objects listed under "retire" in the config. A retired name that is also a desired
    name is never deleted. Objects that are not listed (feedback indexes, the parts-shortages Fabric lakehouse source) are
    never touched. It also applies the service partition and replica counts from the config.

    Authentication uses the Azure CLI admin key for the search service, the same as Update-SearchIndexersAndRebuild.ps1.

.PARAMETER ConfigPath
    Search layout. Defaults to config/search-indexes.json.

.PARAMETER SearchStatePath
    State file written by the original provisioning run. Supplies the ingestion application id and the Search managed
    identity client id used in the SharePoint connection string.

.PARAMETER Recreate
    Delete and rebuild each index (and its indexers) instead of updating it. Required when vector or key fields change.

.PARAMETER Prune
    Delete the retired objects after the new ones are built and the knowledge sources are repointed.

.PARAMETER SkipRun
    Create everything but do not trigger the indexers.

.EXAMPLE
    .\scripts\Provision-SearchIndexes.ps1 -Recreate -Prune
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\search-indexes.json'),
    [string]$PolicyPath = (Join-Path $PSScriptRoot '..\config\governance-policy.json'),
    [string]$SearchStatePath = (Join-Path $PSScriptRoot '..\.state\search.json'),
    [switch]$Recreate,
    [switch]$Prune,
    [switch]$SkipRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$config = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
$policy = Get-Content -Raw -Path $PolicyPath | ConvertFrom-Json
$state = Get-Content -Raw -Path $SearchStatePath | ConvertFrom-Json
$service = $config.service
$endpoint = "https://$($service.name).search.windows.net"
$apiVersion = $service.apiVersion

$adminKey = az search admin-key show --resource-group $service.resourceGroup --service-name $service.name --query primaryKey -o tsv
if ($LASTEXITCODE -ne 0 -or -not $adminKey) { throw 'Could not read the search admin key. Run az login and retry.' }
$tenantId = az account show --query tenantId -o tsv
$script:Headers = @{ 'api-key' = $adminKey.Trim(); 'Content-Type' = 'application/json' }

function Invoke-Search {
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'PUT', 'POST', 'DELETE')][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        $Body = $null,
        [switch]$AllowNotFound
    )
    $uri = "$endpoint/$Path" + $(if ($Path.Contains('?')) { '&' } else { '?' }) + "api-version=$apiVersion"
    $parameters = @{ Method = $Method; Uri = $uri; Headers = $script:Headers }
    if ($null -ne $Body) { $parameters.Body = ConvertTo-Json -InputObject $Body -Depth 30 -Compress }
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try { return Invoke-RestMethod @parameters }
        catch {
            $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
            if ($AllowNotFound -and $status -eq 404) { return $null }
            if ($status -in 429, 500, 503 -and $attempt -lt 5) { Start-Sleep -Seconds ([Math]::Pow(2, $attempt)); continue }
            $detail = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
            throw "Search $Method $Path failed (HTTP $status): $detail"
        }
    }
}

function Get-Prop {
    param($Object, [string]$Name)
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

# ---- service capacity ----------------------------------------------------------------------------------------
$current = az search service show --resource-group $service.resourceGroup --name $service.name --query '{p:partitionCount,r:replicaCount}' -o json | ConvertFrom-Json
if ($current.p -ne $service.partitionCount -or $current.r -ne $service.replicaCount) {
    Write-Host "Scaling $($service.name) to $($service.partitionCount) partition(s) and $($service.replicaCount) replica(s)..."
    az search service update --resource-group $service.resourceGroup --name $service.name --partition-count $service.partitionCount --replica-count $service.replicaCount --only-show-errors | Out-Null
}
else {
    Write-Host "Service capacity already $($service.partitionCount) partition(s) x $($service.replicaCount) replica(s)."
}

# ---- governance columns exposed to search --------------------------------------------------------------------
# DocumentIteration is retired in favour of LifecycleStatus, so it is neither indexed nor requested from SharePoint.
$retiredColumns = @('DocumentIteration')
$retiredFields = @('document_iteration')
$governanceProjection = @($policy.searchProjection | Where-Object { $retiredFields -notcontains $_.name })
$governanceFields = @($policy.searchIndexFields | Where-Object { $retiredFields -notcontains $_.name })
$baseColumns = @('ArtifactId', 'KnowledgeCategory', 'SourceTable', 'SourceSystem', 'ProfileGeneratedAt')

# The SharePoint indexer resolves additionalColumns by display name. Microsoft Purview adds a built-in read-only
# "Sensitivity" label column to every library, so asking for our column by its internal name "Sensitivity" returns
# that empty column. Ask for our column by its own display name instead.
function Resolve-IndexerColumn {
    param([string]$Column)
    $definition = @($policy.sharePointColumns | Where-Object { $_.name -eq $Column }) | Select-Object -First 1
    if ($Column -eq 'Sensitivity' -and $definition) { return $definition.displayName }
    return $Column
}
$additionalColumns = @($baseColumns + @($governanceProjection | ForEach-Object { $_.column }) |
        Where-Object { $retiredColumns -notcontains $_ } | Select-Object -Unique | ForEach-Object { Resolve-IndexerColumn $_ })

function New-IndexDefinition {
    param($Index)
    $embedding = $config.embedding
    $fields = [System.Collections.Generic.List[object]]::new()
    $fields.AddRange(@(
            @{ name = 'chunk_id'; type = 'Edm.String'; key = $true; filterable = $true; analyzer = 'keyword' },
            @{ name = 'parent_id'; type = 'Edm.String'; filterable = $true },
            @{ name = 'chunk'; type = 'Edm.String'; searchable = $true; retrievable = $true },
            @{ name = 'chunk_vector'; type = 'Collection(Edm.Single)'; searchable = $true; retrievable = $false; stored = $false; dimensions = $embedding.dimensions; vectorSearchProfile = $Index.vectorProfile },
            @{ name = 'title'; type = 'Edm.String'; searchable = $true; filterable = $true; sortable = $true; retrievable = $true },
            @{ name = 'document_url'; type = 'Edm.String'; retrievable = $true },
            @{ name = 'document_path'; type = 'Edm.String'; searchable = $true; filterable = $true; retrievable = $true },
            @{ name = 'file_extension'; type = 'Edm.String'; filterable = $true; facetable = $true; retrievable = $true },
            @{ name = 'content_type'; type = 'Edm.String'; filterable = $true; facetable = $true; retrievable = $true },
            @{ name = 'last_modified'; type = 'Edm.DateTimeOffset'; filterable = $true; sortable = $true; retrievable = $true },
            @{ name = 'artifact_id'; type = 'Edm.String'; searchable = $true; filterable = $true; retrievable = $true },
            @{ name = 'category'; type = 'Edm.String'; searchable = $true; filterable = $true; facetable = $true; retrievable = $true },
            @{ name = 'source_table'; type = 'Edm.String'; searchable = $true; filterable = $true; facetable = $true; retrievable = $true },
            @{ name = 'source_system'; type = 'Edm.String'; searchable = $true; filterable = $true; retrievable = $true },
            @{ name = 'profile_generated_at'; type = 'Edm.DateTimeOffset'; filterable = $true; sortable = $true; retrievable = $true }
        ))
    foreach ($field in $governanceFields) {
        $definition = @{}
        foreach ($property in $field.PSObject.Properties) { $definition[$property.Name] = $property.Value }
        # SharePoint number columns reach the indexer as Edm.Double, so the score cannot be an Edm.Int32 field.
        if ($definition.name -eq 'trust_score') { $definition.type = 'Edm.Double' }
        $fields.Add($definition)
    }
    return @{
        name         = $Index.name
        fields       = $fields.ToArray()
        vectorSearch = @{
            algorithms = @(@{
                    name = $Index.algorithm; kind = $config.vector.algorithm
                    hnswParameters = @{ metric = $config.vector.metric; m = $config.vector.m; efConstruction = $config.vector.efConstruction; efSearch = $config.vector.efSearch }
                })
            profiles   = @(@{ name = $Index.vectorProfile; algorithm = $Index.algorithm; vectorizer = $Index.vectorizer })
            vectorizers = @(@{
                    name = $Index.vectorizer; kind = 'azureOpenAI'
                    azureOpenAIParameters = @{ resourceUri = $embedding.endpoint; deploymentId = $embedding.deployment; modelName = $embedding.model }
                })
        }
        semantic     = @{
            defaultConfiguration = $Index.semanticConfiguration
            configurations       = @(@{
                    name = $Index.semanticConfiguration
                    prioritizedFields = @{
                        titleField                = @{ fieldName = 'title' }
                        prioritizedContentFields  = @(@{ fieldName = 'chunk' })
                        prioritizedKeywordsFields = @(@{ fieldName = 'category' }, @{ fieldName = 'document_type' }, @{ fieldName = 'process_area' })
                    }
                })
        }
    }
}

function New-SkillsetDefinition {
    param($Index)
    $chunking = $config.chunking
    $embedding = $config.embedding
    $mappings = [System.Collections.Generic.List[object]]::new()
    $mappings.AddRange(@(
            @{ name = 'chunk'; source = '/document/pages/*' },
            @{ name = 'chunk_vector'; source = '/document/pages/*/chunk_vector' },
            @{ name = 'title'; source = '/document/metadata_spo_item_name' },
            @{ name = 'document_url'; source = '/document/metadata_spo_item_weburi' },
            @{ name = 'document_path'; source = '/document/metadata_spo_item_path' },
            @{ name = 'file_extension'; source = '/document/metadata_spo_item_extension' },
            @{ name = 'content_type'; source = '/document/metadata_spo_item_content_type' },
            @{ name = 'last_modified'; source = '/document/metadata_spo_item_last_modified' },
            @{ name = 'artifact_id'; source = '/document/ArtifactId' },
            @{ name = 'category'; source = '/document/KnowledgeCategory' },
            @{ name = 'source_table'; source = '/document/SourceTable' },
            @{ name = 'source_system'; source = '/document/SourceSystem' },
            @{ name = 'profile_generated_at'; source = '/document/ProfileGeneratedAt' }
        ))
    foreach ($projection in $governanceProjection) {
        $source = Resolve-IndexerColumn $projection.column
        # Names with spaces must be escaped in enrichment paths.
        if ($source -match '\s') { $source = "~2$source~2" }
        $mappings.Add(@{ name = $projection.name; source = "/document/$source" })
    }
    return @{
        name        = $Index.skillset
        description = "Token-aware chunking and integrated vectorization for $($Index.name)."
        skills      = @(
            @{
                '@odata.type' = '#Microsoft.Skills.Text.SplitSkill'
                name = 'split-content'
                description = "Split documents into $($chunking.maximumPageLength)-token pages with $($chunking.pageOverlapLength)-token overlap."
                context = '/document'
                defaultLanguageCode = $chunking.language
                textSplitMode = 'pages'
                unit = $chunking.unit
                azureOpenAITokenizerParameters = @{ encoderModelName = $chunking.tokenizer }
                maximumPageLength = $chunking.maximumPageLength
                pageOverlapLength = $chunking.pageOverlapLength
                inputs = @(@{ name = 'text'; source = '/document/content' })
                outputs = @(@{ name = 'textItems'; targetName = 'pages' })
            },
            @{
                '@odata.type' = '#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill'
                name = 'embed-chunks'
                description = "Create $($embedding.dimensions)-dimensional vectors with the Search managed identity."
                context = '/document/pages/*'
                resourceUri = $embedding.endpoint
                deploymentId = $embedding.deployment
                modelName = $embedding.model
                dimensions = $embedding.dimensions
                inputs = @(@{ name = 'text'; source = '/document/pages/*' })
                outputs = @(@{ name = 'embedding'; targetName = 'chunk_vector' })
            }
        )
        indexProjections = @{
            selectors  = @(@{ targetIndexName = $Index.name; parentKeyFieldName = 'parent_id'; sourceContext = '/document/pages/*'; mappings = $mappings.ToArray() })
            parameters = @{ projectionMode = 'skipIndexingParentDocuments' }
        }
    }
}

function New-DatasourceDefinition {
    param($Source)
    $libraries = ($Source.libraryUrls | ForEach-Object { "includeLibrary=$_" }) -join ';'
    $query = "$libraries;additionalColumns=$($additionalColumns -join ',')"
    $connection = "SharePointOnlineEndpoint=$($Source.siteUrl);ApplicationId=$($state.ingestionApplicationId);TenantId=$tenantId;FederatedCredentialApplicationId=$($state.searchManagedIdentityClientId)"
    return @{
        name        = $Source.datasource
        type        = 'sharepoint'
        credentials = @{ connectionString = $connection }
        container   = @{ name = 'useQuery'; query = $query }
    }
}

function New-IndexerDefinition {
    param($Index, $Source)
    return @{
        name            = $Source.indexer
        description     = "Indexes the $($Source.id) hub libraries in place from SharePoint Online into $($Index.name)."
        dataSourceName  = $Source.datasource
        targetIndexName = $Index.name
        skillsetName    = $Index.skillset
        schedule        = @{ interval = $config.indexer.schedule }
        parameters      = @{
            batchSize = $config.indexer.batchSize; maxFailedItems = 0; maxFailedItemsPerBatch = 0
            configuration = @{
                indexedFileNameExtensions = $config.indexer.indexedFileNameExtensions
                dataToExtract = 'contentAndMetadata'
                failOnUnsupportedContentType = $false
                failOnUnprocessableDocument = $false
                indexStorageMetadataOnlyForOversizedDocuments = $false
            }
        }
        fieldMappings   = @(@{ sourceFieldName = 'metadata_spo_site_library_item_id'; targetFieldName = 'chunk_id'; mappingFunction = @{ name = 'base64Encode' } })
    }
}

$desired = @{ indexes = @(); skillsets = @(); datasources = @(); indexers = @() }
foreach ($index in $config.indexes) {
    $desired.indexes += $index.name
    $desired.skillsets += $index.skillset
    foreach ($source in $index.sources) { $desired.datasources += $source.datasource; $desired.indexers += $source.indexer }
}

# ---- build -----------------------------------------------------------------------------------------------------
foreach ($index in $config.indexes) {
    Write-Host "`n=== $($index.name) ===" -ForegroundColor Cyan
    if ($Recreate) {
        # A knowledge source pins its index, so park it on an older compatible index while this one is rebuilt.
        $pinned = Invoke-Search -Method GET -Path "knowledgesources/$($index.knowledgeSource)" -AllowNotFound
        if ($pinned -and $pinned.searchIndexParameters.searchIndexName -eq $index.name) {
            $semantic = $pinned.searchIndexParameters.semanticConfigurationName
            $fallback = $null
            foreach ($candidate in $config.retire.indexes) {
                $existing = Invoke-Search -Method GET -Path "indexes/$candidate" -AllowNotFound
                if ($existing -and (@($existing.semantic.configurations | ForEach-Object { $_.name }) -contains $semantic)) { $fallback = $candidate; break }
            }
            if (-not $fallback) { throw "Knowledge source $($index.knowledgeSource) pins $($index.name) and no retired index has semantic configuration '$semantic' to park it on." }
            $fallbackFields = @(((Invoke-Search -Method GET -Path "indexes/$fallback").fields) | ForEach-Object { $_.name })
            $pinned.searchIndexParameters.searchIndexName = $fallback
            $pinned.searchIndexParameters.sourceDataFields = @($pinned.searchIndexParameters.sourceDataFields | Where-Object { $fallbackFields -contains $_.name })
            $pinned.PSObject.Properties.Remove('@odata.context')
            $pinned.PSObject.Properties.Remove('@odata.etag')
            Invoke-Search -Method PUT -Path "knowledgesources/$($index.knowledgeSource)" -Body $pinned | Out-Null
            Write-Host "  parked knowledge source $($index.knowledgeSource) on $fallback"
        }
        foreach ($source in $index.sources) { Invoke-Search -Method DELETE -Path "indexers/$($source.indexer)" -AllowNotFound | Out-Null }
        Invoke-Search -Method DELETE -Path "aliases/$($index.alias)" -AllowNotFound | Out-Null
        Invoke-Search -Method DELETE -Path "indexes/$($index.name)" -AllowNotFound | Out-Null
    }
    Invoke-Search -Method PUT -Path "indexes/$($index.name)" -Body (New-IndexDefinition $index) | Out-Null
    Write-Host "  index ready ($(New-IndexDefinition $index | ForEach-Object { $_.fields.Count }) fields)"
    Invoke-Search -Method PUT -Path "skillsets/$($index.skillset)" -Body (New-SkillsetDefinition $index) | Out-Null
    Write-Host "  skillset $($index.skillset) ready"
    foreach ($source in $index.sources) {
        Invoke-Search -Method PUT -Path "datasources/$($source.datasource)" -Body (New-DatasourceDefinition $source) | Out-Null
        Invoke-Search -Method PUT -Path "indexers/$($source.indexer)" -Body (New-IndexerDefinition $index $source) | Out-Null
        Write-Host "  datasource + indexer ready: $($source.id) ($($source.libraryUrls.Count) librar$(if ($source.libraryUrls.Count -eq 1) { 'y' } else { 'ies' }))"
    }
    Invoke-Search -Method PUT -Path "aliases/$($index.alias)" -Body @{ name = $index.alias; indexes = @($index.name) } | Out-Null
    Write-Host "  alias $($index.alias) -> $($index.name)"

    $knowledgeSource = Invoke-Search -Method GET -Path "knowledgesources/$($index.knowledgeSource)" -AllowNotFound
    if ($knowledgeSource) {
        $parameters = $knowledgeSource.searchIndexParameters
        $parameters.searchIndexName = $index.name
        $sourceFields = @($parameters.sourceDataFields | ForEach-Object { $_.name })
        foreach ($name in @($governanceFields | ForEach-Object { $_.name }) + @('document_url') | Select-Object -Unique) {
            if ($sourceFields -notcontains $name) { $parameters.sourceDataFields += [pscustomobject]@{ name = $name } }
        }
        $knowledgeSource.PSObject.Properties.Remove('@odata.context')
        $knowledgeSource.PSObject.Properties.Remove('@odata.etag')
        Invoke-Search -Method PUT -Path "knowledgesources/$($index.knowledgeSource)" -Body $knowledgeSource | Out-Null
        Write-Host "  knowledge source $($index.knowledgeSource) repointed"
    }
    else {
        Write-Host "  knowledge source $($index.knowledgeSource) not found; run provision_foundry_agent.ps1 to create it" -ForegroundColor Yellow
    }
}

# ---- run -------------------------------------------------------------------------------------------------------
if (-not $SkipRun) {
    foreach ($index in $config.indexes) {
        foreach ($source in $index.sources) {
            # Indexer-level "status" only says the indexer is enabled; lastResult.status says whether a run is executing.
            $status = Invoke-Search -Method GET -Path "indexers/$($source.indexer)/status"
            if ($Recreate -and $status.lastResult -and $status.lastResult.status -eq 'inProgress') {
                Write-Host "$($source.indexer) is already running its first full pass"
                continue
            }
            for ($wait = 0; $wait -lt 30; $wait++) {
                $status = Invoke-Search -Method GET -Path "indexers/$($source.indexer)/status"
                if ($null -eq $status.lastResult -or $status.lastResult.status -ne 'inProgress') { break }
                Start-Sleep -Seconds 10
            }
            Invoke-Search -Method POST -Path "indexers/$($source.indexer)/reset" | Out-Null
            Invoke-Search -Method POST -Path "indexers/$($source.indexer)/run" | Out-Null
            Write-Host "Triggered $($source.indexer)"
        }
    }
}

# ---- retire ----------------------------------------------------------------------------------------------------
if ($Prune) {
    Write-Host "`n=== Retiring superseded objects ===" -ForegroundColor Cyan
    foreach ($kind in 'indexers', 'skillsets', 'datasources', 'indexes') {
        foreach ($name in @($config.retire.$kind)) {
            if ($desired[$kind] -contains $name) { continue }
            $removed = Invoke-Search -Method DELETE -Path "$kind/$name" -AllowNotFound
            Write-Host ("  {0,-12} {1}" -f $kind, $name)
        }
    }
}

# ---- state -----------------------------------------------------------------------------------------------------
$primary = $config.indexes[0]
$state.indexName = $primary.name
$state.dataSourceName = $primary.sources[0].datasource
$state.skillsetName = $primary.skillset
$state.indexerName = $primary.sources[0].indexer
$state.aliasName = $primary.alias
$state.chunkSize = $config.chunking.maximumPageLength
$state.chunkOverlap = $config.chunking.pageOverlapLength
$state.apiVersion = $apiVersion
$state.generatedAt = (Get-Date).ToUniversalTime().ToString('o')
$state | ConvertTo-Json -Depth 6 | Set-Content -Path $SearchStatePath -Encoding utf8
Write-Host "`nSearch layer provisioned." -ForegroundColor Green
