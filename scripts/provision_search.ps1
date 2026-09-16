[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\deployment.json'),
    [string]$TenantId,
    [string]$SubscriptionId,
    [string]$ResourceGroup,
    [string]$SearchServiceName,
    [string]$FoundryResourceName,
    [string]$EmbeddingDeployment,
    [string]$IngestionAppName,
    [ValidatePattern('^[a-z0-9][a-z0-9-]{1,79}$')][string]$ResourceNamePrefix,
    [string]$IndexName = '',
    [string]$FeedbackIndexName,
    [ValidateRange(300, 8000)][int]$ChunkSize,
    [ValidateRange(0, 4000)][int]$ChunkOverlap,
    [switch]$ResetIndexer,
    [switch]$RecreateIndex,
    [string]$SharePointStatePath,
    [string]$SearchStatePath
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
if (-not $PSBoundParameters.ContainsKey('TenantId')) { $TenantId = Get-ConfigValue 'azure.tenantId' }
if (-not $PSBoundParameters.ContainsKey('SubscriptionId')) { $SubscriptionId = Get-ConfigValue 'azure.subscriptionId' }
if (-not $PSBoundParameters.ContainsKey('ResourceGroup')) { $ResourceGroup = Get-ConfigValue 'azure.resourceGroup' }
if (-not $PSBoundParameters.ContainsKey('SearchServiceName')) { $SearchServiceName = Get-ConfigValue 'search.serviceName' }
if (-not $PSBoundParameters.ContainsKey('FoundryResourceName')) { $FoundryResourceName = Get-ConfigValue 'foundry.embeddingAccountName' }
if (-not $PSBoundParameters.ContainsKey('EmbeddingDeployment')) { $EmbeddingDeployment = Get-ConfigValue 'search.embeddingDeployment' }
if (-not $PSBoundParameters.ContainsKey('IngestionAppName')) { $IngestionAppName = Get-ConfigValue 'search.ingestionApplicationName' }
if (-not $PSBoundParameters.ContainsKey('ResourceNamePrefix')) { $ResourceNamePrefix = Get-ConfigValue 'search.resourceNamePrefix' }
if (-not $PSBoundParameters.ContainsKey('FeedbackIndexName')) { $FeedbackIndexName = Get-ConfigValue 'search.feedbackIndexName' }
if (-not $PSBoundParameters.ContainsKey('ChunkSize')) { $ChunkSize = Get-ConfigValue 'search.chunkSize' }
if (-not $PSBoundParameters.ContainsKey('ChunkOverlap')) { $ChunkOverlap = Get-ConfigValue 'search.chunkOverlap' }
if (-not $PSBoundParameters.ContainsKey('SharePointStatePath')) {
    $SharePointStatePath = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.sharePointState')
}
if (-not $PSBoundParameters.ContainsKey('SearchStatePath')) {
    $SearchStatePath = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.searchState')
}
$SearchApiVersion = Get-ConfigValue 'apiVersions.searchService'
$SearchManagementApiVersion = Get-ConfigValue 'apiVersions.searchManagement'
$FoundryApiVersion = Get-ConfigValue 'apiVersions.foundryAccount'
$AuthorizationApiVersion = Get-ConfigValue 'apiVersions.armAuthorization'
$GraphApiVersion = Get-ConfigValue 'apiVersions.graph'
$EmbeddingModel = Get-ConfigValue 'search.embeddingModel'
$EmbeddingDimensions = Get-ConfigValue 'search.embeddingDimensions'
$ChunkUnit = Get-ConfigValue 'search.chunkUnit'
$Tokenizer = Get-ConfigValue 'search.tokenizer'
$CorpusLanguage = Get-ConfigValue 'search.corpusLanguage'
$VectorAlgorithmKind = Get-ConfigValue 'search.vectorAlgorithmKind'
$VectorMetric = Get-ConfigValue 'search.vectorMetric'
$HnswM = Get-ConfigValue 'search.hnswM'
$HnswEfConstruction = Get-ConfigValue 'search.hnswEfConstruction'
$HnswEfSearch = Get-ConfigValue 'search.hnswEfSearch'
$VectorAlgorithmName = Get-ConfigValue 'search.vectorAlgorithmName'
$VectorProfileName = Get-ConfigValue 'search.vectorProfileName'
$VectorizerName = Get-ConfigValue 'search.vectorizerName'
$SemanticConfigurationName = Get-ConfigValue 'search.semanticConfigurationName'
$ScheduleInterval = Get-ConfigValue 'search.scheduleInterval'
$IndexerBatchSize = Get-ConfigValue 'search.indexerBatchSize'
$IndexNameSuffix = Get-ConfigValue 'search.indexNameSuffix'
$DataSourceNameSuffix = Get-ConfigValue 'search.dataSourceNameSuffix'
$SkillsetNameSuffix = Get-ConfigValue 'search.skillsetNameSuffix'
$IndexerNameSuffix = Get-ConfigValue 'search.indexerNameSuffix'
$IndexedFileNameExtensions = @($config.corpus.formats | ForEach-Object { ".$($_)" }) -join ','
$GraphAppId = '00000003-0000-0000-c000-000000000000'
if ($ChunkOverlap -ge $ChunkSize) {
    throw 'ChunkOverlap must be smaller than ChunkSize.'
}

function Get-JwtClaims {
    param([Parameter(Mandatory)][string]$Token)
    $payload = $Token.Split('.')[1].Replace('-', '+').Replace('_', '/')
    while ($payload.Length % 4) { $payload += '=' }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) |
        ConvertFrom-Json
}

function Invoke-Graph {
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'POST', 'PATCH', 'DELETE')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [object]$Body,
        [switch]$AllowNotFound,
        [switch]$AllowConflict
    )
    $requestUri = if ($Uri.StartsWith('https://')) { $Uri } else { "https://graph.microsoft.com/$GraphApiVersion$Uri" }
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $parameters = @{
                Method = $Method
                Uri = $requestUri
                Headers = @{ Authorization = "Bearer $script:GraphToken" }
            }
            if ($null -ne $Body) {
                $parameters.Body = $Body | ConvertTo-Json -Depth 30 -Compress
                $parameters.ContentType = 'application/json'
            }
            return Invoke-RestMethod @parameters
        }
        catch {
            $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
            if ($AllowNotFound -and $status -eq 404) { return $null }
            if ($AllowConflict -and $status -eq 409) { return $null }
            if (($status -eq 429 -or $status -ge 500) -and $attempt -lt 5) {
                [Threading.Thread]::Sleep([Math]::Pow(2, $attempt) * 1000)
                continue
            }
            $details = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
            throw "Microsoft Graph $Method $requestUri failed ($status): $details"
        }
    }
}

function Invoke-Search {
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'PUT', 'POST', 'DELETE')][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body,
        [switch]$AllowConflict,
        [switch]$AllowNotFound
    )
    $separator = if ($Path.Contains('?')) { '&' } else { '?' }
    $requestUri = "$script:SearchEndpoint/$Path${separator}api-version=$SearchApiVersion"
    try {
        $parameters = @{
            Method = $Method
            Uri = $requestUri
            Headers = @{ 'api-key' = $script:SearchAdminKey }
        }
        if ($null -ne $Body) {
            $parameters.Body = $Body | ConvertTo-Json -Depth 40 -Compress
            $parameters.ContentType = 'application/json'
        }
        return Invoke-RestMethod @parameters
    }
    catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        if ($AllowConflict -and $status -eq 409) { return $null }
        if ($AllowNotFound -and $status -eq 404) { return $null }
        $details = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
        throw "Azure AI Search $Method $requestUri failed ($status): $details"
    }
}

function Get-AzBearerToken {
    param([Parameter(Mandatory)][string]$ResourceUrl)

    $result = Get-AzAccessToken -ResourceUrl $ResourceUrl -TenantId $TenantId
    if ($result.Token -is [Security.SecureString]) {
        return [Net.NetworkCredential]::new('', $result.Token).Password
    }
    return [string]$result.Token
}

function Invoke-Arm {
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'PUT', 'POST')][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body
    )

    $requestUri = if ($Path.StartsWith('https://')) { $Path } else { "https://management.azure.com$Path" }
    $parameters = @{
        Method = $Method
        Uri = $requestUri
        Headers = @{ Authorization = "Bearer $script:ArmToken" }
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 20 -Compress
        $parameters.ContentType = 'application/json'
    }
    try {
        return Invoke-RestMethod @parameters
    }
    catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        $details = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
        throw "Azure Resource Manager $Method $requestUri failed ($status): $details"
    }
}

if (-not (Test-Path $SharePointStatePath)) {
    throw "SharePoint state not found at $SharePointStatePath. Run provision_sharepoint.ps1 first."
}
$sharePoint = Get-Content $SharePointStatePath -Raw | ConvertFrom-Json

$context = Get-AzContext
if (-not $context -or $context.Subscription.Id -ne $SubscriptionId -or $context.Tenant.Id -ne $TenantId) {
    throw "Azure PowerShell must be connected to subscription $SubscriptionId in tenant $TenantId."
}
$script:ArmToken = Get-AzBearerToken -ResourceUrl 'https://management.azure.com'
$searchResourcePath = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Search/searchServices/$SearchServiceName"
$search = Invoke-Arm -Method GET -Path "$searchResourcePath`?api-version=$SearchManagementApiVersion"
if ($search.sku.name -eq 'free') { throw 'The SharePoint indexer requires Basic tier or higher.' }
if ($search.identity.type -notmatch 'SystemAssigned') {
    throw "Search service $SearchServiceName must have a system-assigned managed identity."
}

$script:GraphToken = Get-AzBearerToken -ResourceUrl 'https://graph.microsoft.com'
$claims = Get-JwtClaims -Token $script:GraphToken
$scopes = @($claims.scp -split ' ')
$requiredScopes = @('Application.ReadWrite.All', 'AppRoleAssignment.ReadWrite.All')
$missingScopes = @($requiredScopes | Where-Object { $scopes -notcontains $_ })
if ($missingScopes.Count) {
    throw "The Graph token is missing delegated scopes: $($missingScopes -join ', ')."
}

$graphServicePrincipals = Invoke-Graph -Method GET -Uri "/servicePrincipals?`$filter=appId eq '$GraphAppId'&`$select=id,appId,appRoles"
$graphServicePrincipal = @($graphServicePrincipals.value) | Select-Object -First 1
if (-not $graphServicePrincipal) { throw 'Microsoft Graph service principal was not found.' }
$requiredGraphRoles = @('Files.Read.All', 'Sites.Read.All')
$graphRoleIds = @{}
foreach ($roleName in $requiredGraphRoles) {
    $role = @($graphServicePrincipal.appRoles) | Where-Object {
        $_.value -eq $roleName -and $_.allowedMemberTypes -contains 'Application'
    } | Select-Object -First 1
    if (-not $role) { throw "Microsoft Graph application role $roleName was not found." }
    $graphRoleIds[$roleName] = $role.id
}

$encodedAppName = [Uri]::EscapeDataString("displayName eq '$IngestionAppName'")
$applications = Invoke-Graph -Method GET -Uri "/applications?`$filter=$encodedAppName&`$select=id,appId,displayName,requiredResourceAccess,passwordCredentials,keyCredentials"
if (@($applications.value).Count -gt 1) {
    throw "Multiple Entra applications are named '$IngestionAppName'; refusing an ambiguous update."
}
$application = @($applications.value) | Select-Object -First 1
$requiredResourceAccess = @(
    @{
        resourceAppId = $GraphAppId
        resourceAccess = @(
            $requiredGraphRoles | ForEach-Object { @{ id = $graphRoleIds[$_]; type = 'Role' } }
        )
    }
)
if (-not $application) {
    Write-Host "Creating Entra ingestion app '$IngestionAppName'..."
    $application = Invoke-Graph -Method POST -Uri '/applications' -Body @{
        displayName = $IngestionAppName
        signInAudience = 'AzureADMyOrg'
        requiredResourceAccess = $requiredResourceAccess
    }
}
else {
    if (@($application.passwordCredentials).Count -or @($application.keyCredentials).Count) {
        throw "The standing ingestion app $($application.appId) contains a password or certificate; remove it before provisioning."
    }
    Invoke-Graph -Method PATCH -Uri "/applications/$($application.id)" -Body @{
        requiredResourceAccess = $requiredResourceAccess
    } | Out-Null
}

$applicationServicePrincipals = Invoke-Graph -Method GET -Uri "/servicePrincipals?`$filter=appId eq '$($application.appId)'&`$select=id,appId,displayName"
if (@($applicationServicePrincipals.value).Count -gt 1) {
    throw "Multiple service principals exist for ingestion app $($application.appId)."
}
$applicationServicePrincipal = @($applicationServicePrincipals.value) | Select-Object -First 1
if (-not $applicationServicePrincipal) {
    $applicationServicePrincipal = Invoke-Graph -Method POST -Uri '/servicePrincipals' -Body @{
        appId = $application.appId
    }
}
$applicationPostcondition = Invoke-Graph -Method GET -Uri "/applications/$($application.id)?`$select=id,passwordCredentials,keyCredentials"
$servicePrincipalPostcondition = Invoke-Graph -Method GET -Uri "/servicePrincipals/$($applicationServicePrincipal.id)?`$select=id,passwordCredentials,keyCredentials"
if (@($applicationPostcondition.passwordCredentials).Count -or @($applicationPostcondition.keyCredentials).Count -or
    @($servicePrincipalPostcondition.passwordCredentials).Count -or @($servicePrincipalPostcondition.keyCredentials).Count) {
    throw "The standing ingestion identity contains a password or certificate credential (application=$($application.id), servicePrincipal=$($applicationServicePrincipal.id))."
}

$assignments = Invoke-Graph -Method GET -Uri "/servicePrincipals/$($applicationServicePrincipal.id)/appRoleAssignments"
$requiredRoleIds = @($requiredGraphRoles | ForEach-Object { $graphRoleIds[$_] })
foreach ($assignment in @($assignments.value)) {
    $isExpected = $assignment.resourceId -eq $graphServicePrincipal.id -and $requiredRoleIds -contains $assignment.appRoleId
    if (-not $isExpected) {
        Invoke-Graph -Method DELETE -Uri "/servicePrincipals/$($applicationServicePrincipal.id)/appRoleAssignments/$($assignment.id)" | Out-Null
    }
}
foreach ($roleName in $requiredGraphRoles) {
    $roleId = $graphRoleIds[$roleName]
    $exists = @($assignments.value) | Where-Object {
        $_.resourceId -eq $graphServicePrincipal.id -and $_.appRoleId -eq $roleId
    }
    if (-not $exists) {
        Invoke-Graph -Method POST -Uri "/servicePrincipals/$($applicationServicePrincipal.id)/appRoleAssignments" -Body @{
            principalId = $applicationServicePrincipal.id
            resourceId = $graphServicePrincipal.id
            appRoleId = $roleId
        } | Out-Null
    }
}

$managedIdentity = Invoke-Graph -Method GET -Uri "/servicePrincipals/$($search.identity.principalId)?`$select=id,appId,displayName"
$federatedCredentials = Invoke-Graph -Method GET -Uri "/applications/$($application.id)/federatedIdentityCredentials"
$federatedName = 'search-managed-identity'
$federatedCredential = @($federatedCredentials.value) | Where-Object { $_.name -eq $federatedName } | Select-Object -First 1
$expectedIssuer = "https://login.microsoftonline.com/$TenantId/v2.0"
foreach ($credential in @($federatedCredentials.value)) {
    $expectedAudience = @($credential.audiences).Count -eq 1 -and $credential.audiences[0] -eq 'api://AzureADTokenExchange'
    $isExpected = $credential.name -eq $federatedName -and
        $credential.issuer -eq $expectedIssuer -and
        $credential.subject -eq $search.identity.principalId -and
        $expectedAudience
    if (-not $isExpected) {
        Invoke-Graph -Method DELETE -Uri "/applications/$($application.id)/federatedIdentityCredentials/$($credential.id)" | Out-Null
        if ($credential.name -eq $federatedName) { $federatedCredential = $null }
    }
}
if (-not $federatedCredential) {
    $federatedCredential = Invoke-Graph -Method POST -Uri "/applications/$($application.id)/federatedIdentityCredentials" -Body @{
        name = $federatedName
        description = "Trust the system-assigned identity of $SearchServiceName."
        issuer = $expectedIssuer
        subject = $search.identity.principalId
        audiences = @('api://AzureADTokenExchange')
    }
}

$script:SearchEndpoint = "https://$SearchServiceName.search.windows.net"
$searchKeys = Invoke-Arm -Method POST -Path "$searchResourcePath/listAdminKeys?api-version=$SearchManagementApiVersion"
$script:SearchAdminKey = $searchKeys.primaryKey
if (-not $script:SearchAdminKey) { throw 'Could not obtain an ephemeral Search admin key.' }
$foundryResourcePath = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$FoundryResourceName"
$foundry = Invoke-Arm -Method GET -Path "$foundryResourcePath`?api-version=$FoundryApiVersion"
$openAiEndpoint = "https://$($foundry.properties.customSubDomainName).openai.azure.com"

$openAiUserRoleId = "/subscriptions/$SubscriptionId/providers/Microsoft.Authorization/roleDefinitions/5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
$roleAssignments = Invoke-Arm -Method GET -Path "$($foundry.id)/providers/Microsoft.Authorization/roleAssignments?api-version=$AuthorizationApiVersion&`$filter=atScope()"
$hasOpenAiRole = @($roleAssignments.value) | Where-Object {
    $_.properties.principalId -eq $search.identity.principalId -and
    $_.properties.roleDefinitionId -eq $openAiUserRoleId
} | Select-Object -First 1
if (-not $hasOpenAiRole) {
    $roleAssignmentId = [Guid]::NewGuid().ToString()
    Invoke-Arm -Method PUT -Path "$($foundry.id)/providers/Microsoft.Authorization/roleAssignments/$roleAssignmentId`?api-version=$AuthorizationApiVersion" -Body @{
        properties = @{
            roleDefinitionId = $openAiUserRoleId
            principalId = $search.identity.principalId
            principalType = 'ServicePrincipal'
        }
    } | Out-Null
}

$indexName = if ($IndexName) { $IndexName } else { "$ResourceNamePrefix-$IndexNameSuffix" }
$feedbackIndexName = $FeedbackIndexName
$dataSourceName = "$ResourceNamePrefix-$DataSourceNameSuffix"
$skillsetName = "$ResourceNamePrefix-$SkillsetNameSuffix"
$indexerName = "$ResourceNamePrefix-$IndexerNameSuffix"

if ($RecreateIndex) {
    Invoke-Search -Method DELETE -Path "indexers/$indexerName" -AllowNotFound | Out-Null
    Invoke-Search -Method DELETE -Path "indexes/$indexName" -AllowNotFound | Out-Null
}

$indexDefinition = @{
    name = $indexName
    fields = @(
        @{ name = 'chunk_id'; type = 'Edm.String'; key = $true; filterable = $true; analyzer = 'keyword' },
        @{ name = 'parent_id'; type = 'Edm.String'; filterable = $true },
        @{ name = 'chunk'; type = 'Edm.String'; searchable = $true; retrievable = $true },
        @{ name = 'chunk_vector'; type = 'Collection(Edm.Single)'; searchable = $true; retrievable = $false; stored = $false; dimensions = $EmbeddingDimensions; vectorSearchProfile = $VectorProfileName },
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
    )
    vectorSearch = @{
        algorithms = @(
            @{
                name = $VectorAlgorithmName
                kind = $VectorAlgorithmKind
                hnswParameters = @{
                    metric = $VectorMetric
                    m = $HnswM
                    efConstruction = $HnswEfConstruction
                    efSearch = $HnswEfSearch
                }
            }
        )
        profiles = @(
            @{ name = $VectorProfileName; algorithm = $VectorAlgorithmName; vectorizer = $VectorizerName }
        )
        vectorizers = @(
            @{
                name = $VectorizerName
                kind = 'azureOpenAI'
                azureOpenAIParameters = @{
                    resourceUri = $openAiEndpoint
                    deploymentId = $EmbeddingDeployment
                    modelName = $EmbeddingModel
                }
            }
        )
    }
    semantic = @{
        defaultConfiguration = $SemanticConfigurationName
        configurations = @(
            @{
                name = $SemanticConfigurationName
                prioritizedFields = @{
                    titleField = @{ fieldName = 'title' }
                    prioritizedContentFields = @(@{ fieldName = 'chunk' })
                    prioritizedKeywordsFields = @(
                        @{ fieldName = 'category' },
                        @{ fieldName = 'source_table' }
                    )
                }
            }
        )
    }
}
Invoke-Search -Method PUT -Path "indexes/$indexName" -Body $indexDefinition | Out-Null

$feedbackIndexDefinition = @{
    name = $feedbackIndexName
    fields = @(
        @{ name = 'feedback_id'; type = 'Edm.String'; key = $true; filterable = $true },
        @{ name = 'query'; type = 'Edm.String'; searchable = $true; retrievable = $true },
        @{ name = 'chunk_id'; type = 'Edm.String'; filterable = $true; retrievable = $true },
        @{ name = 'parent_id'; type = 'Edm.String'; filterable = $true; retrievable = $true },
        @{ name = 'document_url'; type = 'Edm.String'; retrievable = $true },
        @{ name = 'category'; type = 'Edm.String'; filterable = $true; facetable = $true; retrievable = $true },
        @{ name = 'source_table'; type = 'Edm.String'; filterable = $true; facetable = $true; retrievable = $true },
        @{ name = 'deployment_generation'; type = 'Edm.String'; filterable = $true; facetable = $true; retrievable = $true },
        @{ name = 'rating'; type = 'Edm.Int32'; filterable = $true; sortable = $true; facetable = $true },
        @{ name = 'relevant'; type = 'Edm.Boolean'; filterable = $true; facetable = $true },
        @{ name = 'comment'; type = 'Edm.String'; searchable = $true; retrievable = $true },
        @{ name = 'retrieved_at'; type = 'Edm.DateTimeOffset'; filterable = $true; sortable = $true; retrievable = $true },
        @{ name = 'created_at'; type = 'Edm.DateTimeOffset'; filterable = $true; sortable = $true; retrievable = $true }
    )
}
Invoke-Search -Method PUT -Path "indexes/$feedbackIndexName" -Body $feedbackIndexDefinition | Out-Null

$projectionMappings = @(
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
)
$skillsetDefinition = @{
    name = $skillsetName
    description = 'Token-aware chunking and integrated vectorization for SharePoint semiconductor documents.'
    skills = @(
        @{
            '@odata.type' = '#Microsoft.Skills.Text.SplitSkill'
            name = 'split-content'
            description = "Split documents into $ChunkSize-token pages with $ChunkOverlap-token overlap."
            context = '/document'
            defaultLanguageCode = $CorpusLanguage
            textSplitMode = 'pages'
            unit = $ChunkUnit
            azureOpenAITokenizerParameters = @{ encoderModelName = $Tokenizer }
            maximumPageLength = $ChunkSize
            pageOverlapLength = $ChunkOverlap
            inputs = @(@{ name = 'text'; source = '/document/content' })
            outputs = @(@{ name = 'textItems'; targetName = 'pages' })
        },
        @{
            '@odata.type' = '#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill'
            name = 'embed-chunks'
            description = "Create $EmbeddingDimensions-dimensional vectors with the Search managed identity."
            context = '/document/pages/*'
            resourceUri = $openAiEndpoint
            deploymentId = $EmbeddingDeployment
            modelName = $EmbeddingModel
            dimensions = $EmbeddingDimensions
            inputs = @(@{ name = 'text'; source = '/document/pages/*' })
            outputs = @(@{ name = 'embedding'; targetName = 'chunk_vector' })
        }
    )
    indexProjections = @{
        selectors = @(
            @{
                targetIndexName = $indexName
                parentKeyFieldName = 'parent_id'
                sourceContext = '/document/pages/*'
                mappings = $projectionMappings
            }
        )
        parameters = @{ projectionMode = 'skipIndexingParentDocuments' }
    }
}
Invoke-Search -Method PUT -Path "skillsets/$skillsetName" -Body $skillsetDefinition | Out-Null

$libraryQuery = "includeLibrary=$($sharePoint.libraryUrl);additionalColumns=ArtifactId,KnowledgeCategory,SourceTable,SourceSystem,ProfileGeneratedAt"
$connectionString = "SharePointOnlineEndpoint=$($sharePoint.siteUrl);ApplicationId=$($application.appId);TenantId=$TenantId;FederatedCredentialApplicationId=$($managedIdentity.appId)"
$dataSourceDefinition = @{
    name = $dataSourceName
    type = 'sharepoint'
    credentials = @{ connectionString = $connectionString }
    container = @{ name = 'useQuery'; query = $libraryQuery }
}
Invoke-Search -Method PUT -Path "datasources/$dataSourceName" -Body $dataSourceDefinition | Out-Null

$indexerDefinition = @{
    name = $indexerName
    description = 'Direct SharePoint Online ingestion with no intermediate Blob copy.'
    dataSourceName = $dataSourceName
    targetIndexName = $indexName
    skillsetName = $skillsetName
    schedule = @{ interval = $ScheduleInterval }
    parameters = @{
        batchSize = $IndexerBatchSize
        maxFailedItems = 0
        maxFailedItemsPerBatch = 0
        configuration = @{
            indexedFileNameExtensions = $IndexedFileNameExtensions
            dataToExtract = 'contentAndMetadata'
            failOnUnsupportedContentType = $false
            failOnUnprocessableDocument = $false
            indexStorageMetadataOnlyForOversizedDocuments = $false
        }
    }
    fieldMappings = @(
        @{
            sourceFieldName = 'metadata_spo_site_library_item_id'
            targetFieldName = 'chunk_id'
            mappingFunction = @{ name = 'base64Encode' }
        }
    )
}
Invoke-Search -Method PUT -Path "indexers/$indexerName" -Body $indexerDefinition | Out-Null
if ($ResetIndexer) {
    Invoke-Search -Method POST -Path "indexers/$indexerName/reset" -AllowConflict | Out-Null
}
$indexerTriggeredAt = (Get-Date).ToUniversalTime().ToString('o')
Invoke-Search -Method POST -Path "indexers/$indexerName/run" -AllowConflict | Out-Null

$state = [ordered]@{
    subscriptionId = $SubscriptionId
    resourceGroup = $ResourceGroup
    searchServiceName = $SearchServiceName
    resourceNamePrefix = $ResourceNamePrefix
    searchEndpoint = $script:SearchEndpoint
    searchPortalUrl = "https://portal.azure.com/#resource$($search.id)/overview"
    indexName = $indexName
    feedbackIndexName = $feedbackIndexName
    indexPortalUrl = "https://portal.azure.com/#resource$($search.id)/searchExplorer"
    dataSourceName = $dataSourceName
    skillsetName = $skillsetName
    indexerName = $indexerName
    ingestionApplicationId = $application.appId
    ingestionApplicationObjectId = $application.id
    searchManagedIdentityPrincipalId = $search.identity.principalId
    searchManagedIdentityClientId = $managedIdentity.appId
    embeddingEndpoint = $openAiEndpoint
    embeddingDeployment = $EmbeddingDeployment
    chunkSize = $ChunkSize
    chunkOverlap = $ChunkOverlap
    indexerTriggeredAt = $indexerTriggeredAt
    apiVersion = $SearchApiVersion
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
}
$stateDirectory = Split-Path $SearchStatePath -Parent
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$state | ConvertTo-Json -Depth 6 | Set-Content -Path $SearchStatePath -Encoding utf8
$state | ConvertTo-Json -Depth 6

Remove-Variable GraphToken -Scope Script -ErrorAction SilentlyContinue
Remove-Variable ArmToken -Scope Script -ErrorAction SilentlyContinue
Remove-Variable SearchAdminKey -Scope Script -ErrorAction SilentlyContinue