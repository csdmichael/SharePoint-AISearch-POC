[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\deployment.json'),
    [switch]$SkipSmokeTest
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

$tenantId = Get-ConfigValue 'azure.tenantId'
$subscriptionId = Get-ConfigValue 'azure.subscriptionId'
$resourceGroup = Get-ConfigValue 'azure.resourceGroup'
$searchServiceName = Get-ConfigValue 'search.serviceName'
$indexAliasName = Get-ConfigValue 'search.indexAliasName'
$semanticConfigurationName = Get-ConfigValue 'search.semanticConfigurationName'
$accountName = Get-ConfigValue 'foundry.knowledgeAgent.accountName'
$projectName = Get-ConfigValue 'foundry.knowledgeAgent.projectName'
$agentName = Get-ConfigValue 'foundry.knowledgeAgent.agentName'
$agentModel = Get-ConfigValue 'foundry.knowledgeAgent.agentModelDeployment'
$agentReasoningEffort = Get-ConfigValue 'foundry.knowledgeAgent.agentReasoningEffort'
$knowledgeBaseModel = Get-ConfigValue 'foundry.knowledgeAgent.knowledgeBaseModelDeployment'
$knowledgeSourceName = Get-ConfigValue 'foundry.knowledgeAgent.knowledgeSourceName'
$knowledgeBaseName = Get-ConfigValue 'foundry.knowledgeAgent.knowledgeBaseName'
$connectionName = Get-ConfigValue 'foundry.knowledgeAgent.connectionName'
$retrievalReasoningEffort = Get-ConfigValue 'foundry.knowledgeAgent.retrievalReasoningEffort'
$outputMode = Get-ConfigValue 'foundry.knowledgeAgent.outputMode'
$knowledgeSourceDescription = Get-ConfigValue 'foundry.knowledgeAgent.knowledgeSourceDescription'
$knowledgeBaseDescription = Get-ConfigValue 'foundry.knowledgeAgent.knowledgeBaseDescription'
$retrievalInstructions = Get-ConfigValue 'foundry.knowledgeAgent.retrievalInstructions'
$answerInstructions = Get-ConfigValue 'foundry.knowledgeAgent.answerInstructions'
$smokeTestQuery = Get-ConfigValue 'foundry.knowledgeAgent.smokeTestQuery'
$instructionsPath = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'foundry.knowledgeAgent.instructionsPath')
$statePath = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.foundryState')
$authorizationApiVersion = Get-ConfigValue 'apiVersions.armAuthorization'
$foundryApiVersion = Get-ConfigValue 'apiVersions.foundryAccount'
$agentApiVersion = Get-ConfigValue 'apiVersions.foundryAgent'
$connectionApiVersion = Get-ConfigValue 'apiVersions.foundryConnection'
$searchManagementApiVersion = Get-ConfigValue 'apiVersions.searchManagement'
$searchApiVersion = Get-ConfigValue 'apiVersions.searchService'

if (-not (Test-Path $instructionsPath)) { throw "Agent instructions not found: $instructionsPath" }
$agentInstructions = Get-Content $instructionsPath -Raw
if ([string]::IsNullOrWhiteSpace($agentInstructions)) { throw "Agent instructions are empty: $instructionsPath" }

$context = Get-AzContext
if (-not $context -or $context.Subscription.Id -ne $subscriptionId -or $context.Tenant.Id -ne $tenantId) {
    throw "Azure PowerShell must be connected to the subscription and tenant configured in $ConfigPath."
}

function Get-AzBearerToken {
    param([Parameter(Mandatory)][string]$ResourceUrl)

    $result = Get-AzAccessToken -ResourceUrl $ResourceUrl -TenantId $tenantId
    if ($result.Token -is [Security.SecureString]) {
        return [Net.NetworkCredential]::new('', $result.Token).Password
    }
    return [string]$result.Token
}

function Invoke-Arm {
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'PUT', 'PATCH', 'POST')][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body,
        [switch]$AllowConflict
    )

    $requestUri = if ($Path.StartsWith('https://')) { $Path } else { "https://management.azure.com$Path" }
    $parameters = @{
        Method = $Method
        Uri = $requestUri
        Headers = @{ Authorization = "Bearer $script:ArmToken" }
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 30 -Compress
        $parameters.ContentType = 'application/json'
    }
    try {
        return Invoke-RestMethod @parameters
    }
    catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        if ($AllowConflict -and $status -eq 409) { return $null }
        $details = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
        throw "Azure Resource Manager $Method $requestUri failed ($status): $details"
    }
}

function Invoke-Search {
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'PUT')][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body
    )

    $separator = if ($Path.Contains('?')) { '&' } else { '?' }
    $requestUri = "$script:SearchEndpoint/$Path${separator}api-version=$searchApiVersion"
    $parameters = @{
        Method = $Method
        Uri = $requestUri
        Headers = @{ 'api-key' = $script:SearchAdminKey }
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 40 -Compress
        $parameters.ContentType = 'application/json'
    }
    try {
        return Invoke-RestMethod @parameters
    }
    catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        $details = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
        throw "Azure AI Search $Method $requestUri failed ($status): $details"
    }
}

function Invoke-Foundry {
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'POST')][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body
    )

    $requestUri = "$script:ProjectEndpoint/$Path"
    $parameters = @{
        Method = $Method
        Uri = $requestUri
        Headers = @{ Authorization = "Bearer $script:FoundryToken" }
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 50 -Compress
        $parameters.ContentType = 'application/json'
    }
    try {
        return Invoke-RestMethod @parameters
    }
    catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        $details = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
        throw "Microsoft Foundry $Method $requestUri failed ($status): $details"
    }
}

function Ensure-RoleAssignment {
    param(
        [Parameter(Mandatory)][string]$Scope,
        [Parameter(Mandatory)][string]$PrincipalId,
        [Parameter(Mandatory)][string]$RoleDefinitionId
    )

    $roleResourceId = "/subscriptions/$subscriptionId/providers/Microsoft.Authorization/roleDefinitions/$RoleDefinitionId"
    $assignments = Invoke-Arm -Method GET -Path "$Scope/providers/Microsoft.Authorization/roleAssignments?api-version=$authorizationApiVersion&`$filter=atScope()"
    $existing = @($assignments.value) | Where-Object {
        $_.properties.principalId -eq $PrincipalId -and $_.properties.roleDefinitionId -eq $roleResourceId
    } | Select-Object -First 1
    if ($existing) { return $existing }

    $assignmentId = [Guid]::NewGuid().ToString()
    return Invoke-Arm -Method PUT -Path "$Scope/providers/Microsoft.Authorization/roleAssignments/$assignmentId`?api-version=$authorizationApiVersion" -Body @{
        properties = @{
            roleDefinitionId = $roleResourceId
            principalId = $PrincipalId
            principalType = 'ServicePrincipal'
        }
    } -AllowConflict
}

function ConvertTo-FoundrySubscriptionToken {
    param([Parameter(Mandatory)][string]$Value)

    $hex = $Value.Replace('-', '')
    $bytes = for ($offset = 0; $offset -lt $hex.Length; $offset += 2) {
        [Convert]::ToByte($hex.Substring($offset, 2), 16)
    }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

$script:ArmToken = Get-AzBearerToken -ResourceUrl 'https://management.azure.com'
$script:FoundryToken = Get-AzBearerToken -ResourceUrl 'https://ai.azure.com'
$foundryAccountPath = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.CognitiveServices/accounts/$accountName"
$projectPath = "$foundryAccountPath/projects/$projectName"
$searchResourcePath = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.Search/searchServices/$searchServiceName"

$foundryAccount = Invoke-Arm -Method GET -Path "$foundryAccountPath`?api-version=$foundryApiVersion"
$project = Invoke-Arm -Method GET -Path "$projectPath`?api-version=$foundryApiVersion"
$search = Invoke-Arm -Method GET -Path "$searchResourcePath`?api-version=$searchManagementApiVersion"
if ($project.identity.type -notmatch 'SystemAssigned' -or -not $project.identity.principalId) {
    throw "Foundry project $projectName must have a system-assigned managed identity."
}
if ($search.identity.type -notmatch 'SystemAssigned' -or -not $search.identity.principalId) {
    throw "Search service $searchServiceName must have a system-assigned managed identity."
}

$deployments = Invoke-Arm -Method GET -Path "$foundryAccountPath/deployments?api-version=$foundryApiVersion"
foreach ($requiredDeployment in @($agentModel, $knowledgeBaseModel)) {
    $deployment = @($deployments.value) | Where-Object {
        $_.name -eq $requiredDeployment -and $_.properties.provisioningState -eq 'Succeeded'
    } | Select-Object -First 1
    if (-not $deployment) { throw "Required Foundry model deployment is unavailable: $requiredDeployment" }
}

if ($search.properties.authOptions.PSObject.Properties.Name -notcontains 'aadOrApiKey') {
    $search = Invoke-Arm -Method PATCH -Path "$searchResourcePath`?api-version=$searchManagementApiVersion" -Body @{
        properties = @{
            disableLocalAuth = $false
            authOptions = @{
                aadOrApiKey = @{ aadAuthFailureMode = 'http401WithBearerChallenge' }
            }
        }
    }
}

$searchDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
$cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
Ensure-RoleAssignment -Scope $searchResourcePath -PrincipalId $project.identity.principalId -RoleDefinitionId $searchDataReaderRoleId | Out-Null
Ensure-RoleAssignment -Scope $foundryAccountPath -PrincipalId $search.identity.principalId -RoleDefinitionId $cognitiveServicesUserRoleId | Out-Null

$script:SearchEndpoint = "https://$searchServiceName.search.windows.net"
$searchKeys = Invoke-Arm -Method POST -Path "$searchResourcePath/listAdminKeys?api-version=$searchManagementApiVersion"
$script:SearchAdminKey = $searchKeys.primaryKey
if (-not $script:SearchAdminKey) { throw 'Could not obtain an ephemeral Search admin key.' }

$alias = Invoke-Search -Method GET -Path "aliases/$indexAliasName"
if (@($alias.indexes).Count -ne 1) { throw "Search alias $indexAliasName must reference exactly one index." }
$searchIndexName = $alias.indexes[0]
$knowledgeSource = Invoke-Search -Method PUT -Path "knowledgesources/$knowledgeSourceName" -Body @{
    name = $knowledgeSourceName
    kind = 'searchIndex'
    description = $knowledgeSourceDescription
    searchIndexParameters = @{
        searchIndexName = $searchIndexName
        semanticConfigurationName = $semanticConfigurationName
        searchFields = @(
            @{ name = 'chunk' },
            @{ name = 'title' },
            @{ name = 'document_path' },
            @{ name = 'artifact_id' },
            @{ name = 'category' },
            @{ name = 'source_table' },
            @{ name = 'source_system' }
        )
        sourceDataFields = @(
            @{ name = 'chunk_id' },
            @{ name = 'parent_id' },
            @{ name = 'chunk' },
            @{ name = 'title' },
            @{ name = 'document_url' },
            @{ name = 'document_path' },
            @{ name = 'file_extension' },
            @{ name = 'content_type' },
            @{ name = 'last_modified' },
            @{ name = 'artifact_id' },
            @{ name = 'category' },
            @{ name = 'source_table' },
            @{ name = 'source_system' },
            @{ name = 'profile_generated_at' }
        )
    }
}

$openAiEndpoint = "https://$($foundryAccount.properties.customSubDomainName).openai.azure.com"
$knowledgeBase = Invoke-Search -Method PUT -Path "knowledgebases/$knowledgeBaseName" -Body @{
    name = $knowledgeBaseName
    description = $knowledgeBaseDescription
    retrievalInstructions = $retrievalInstructions
    answerInstructions = $answerInstructions
    outputMode = $outputMode
    knowledgeSources = @(@{ name = $knowledgeSourceName })
    models = @(
        @{
            kind = 'azureOpenAI'
            azureOpenAIParameters = @{
                resourceUri = $openAiEndpoint
                deploymentId = $knowledgeBaseModel
                modelName = $knowledgeBaseModel
            }
        }
    )
    retrievalReasoningEffort = @{ kind = $retrievalReasoningEffort }
}

$mcpEndpoint = "$script:SearchEndpoint/knowledgebases/$knowledgeBaseName/mcp?api-version=$searchApiVersion"
$connection = Invoke-Arm -Method PUT -Path "$projectPath/connections/$connectionName`?api-version=$connectionApiVersion" -Body @{
    name = $connectionName
    type = 'Microsoft.MachineLearningServices/workspaces/connections'
    properties = @{
        authType = 'ProjectManagedIdentity'
        category = 'RemoteTool'
        target = $mcpEndpoint
        isSharedToAll = $true
        audience = 'https://search.azure.com/'
        metadata = @{ ApiType = 'Azure' }
    }
}

$script:ProjectEndpoint = if ($project.properties.endpoints.'AI Foundry API') {
    $project.properties.endpoints.'AI Foundry API'.TrimEnd('/')
} else {
    "https://$accountName.services.ai.azure.com/api/projects/$projectName"
}
$agentDefinition = @{
    kind = 'prompt'
    model = $agentModel
    instructions = $agentInstructions
    reasoning = @{ effort = $agentReasoningEffort }
    tools = @(
        @{
            type = 'mcp'
            server_label = 'knowledge-base'
            server_url = $mcpEndpoint
            require_approval = 'never'
            allowed_tools = @('knowledge_base_retrieve')
            project_connection_id = $connectionName
        }
    )
}
$existingAgent = Invoke-Foundry -Method GET -Path "agents/$agentName`?api-version=$agentApiVersion"
$existingDefinition = $existingAgent.versions.latest.definition
$existingTool = @($existingDefinition.tools) | Select-Object -First 1
$agentNeedsUpdate = $existingDefinition.model -ne $agentModel -or
    $existingDefinition.instructions -ne $agentInstructions -or
    $existingDefinition.reasoning.effort -ne $agentReasoningEffort -or
    -not $existingTool -or
    $existingTool.type -ne 'mcp' -or
    $existingTool.server_url -ne $mcpEndpoint -or
    $existingTool.project_connection_id -ne $connectionName -or
    @($existingTool.allowed_tools) -notcontains 'knowledge_base_retrieve'
if ($agentNeedsUpdate) {
    Invoke-Foundry -Method POST -Path "agents/$agentName/versions?api-version=$agentApiVersion" -Body @{
        definition = $agentDefinition
    } | Out-Null
}

$deployedAgent = Invoke-Foundry -Method GET -Path "agents/$agentName`?api-version=$agentApiVersion"
$latest = $deployedAgent.versions.latest
if ($latest.definition.tools[0].server_url -ne $mcpEndpoint) {
    throw "Agent $agentName is not connected to the configured Foundry IQ knowledge base."
}

$smokeTest = $null
if (-not $SkipSmokeTest) {
    $conversation = Invoke-Foundry -Method POST -Path 'openai/v1/conversations' -Body @{}
    $response = Invoke-Foundry -Method POST -Path 'openai/v1/responses' -Body @{
        conversation = $conversation.id
        input = $smokeTestQuery
        agent_reference = @{ type = 'agent_reference'; name = $agentName }
    }
    $responseJson = $response | ConvertTo-Json -Depth 100 -Compress
    $outputText = @(
        $response.output | ForEach-Object {
            if ($_.PSObject.Properties.Name -contains 'content') {
                @($_.content) | Where-Object { $_.type -eq 'output_text' } | ForEach-Object { $_.text }
            }
        }
    ) -join "`n"
    if ([string]::IsNullOrWhiteSpace($outputText)) { throw 'Foundry agent smoke test returned no text.' }
    if ($responseJson -notmatch 'knowledge_base_retrieve') { throw 'Foundry agent smoke test did not call the knowledge base.' }
    $smokeTest = [ordered]@{
        conversationId = $conversation.id
        responseId = $response.id
        outputText = $outputText
        knowledgeToolCalled = $true
    }
}

$encodedSubscription = ConvertTo-FoundrySubscriptionToken -Value $subscriptionId
$agentUrl = "https://ai.azure.com/nextgen/r/$encodedSubscription,$resourceGroup,,$accountName,$projectName/build/agents/$agentName/build?version=$($latest.version)&tid=$tenantId"
$state = [ordered]@{
    subscriptionId = $subscriptionId
    resourceGroup = $resourceGroup
    foundryAccountName = $accountName
    foundryProjectName = $projectName
    projectEndpoint = $script:ProjectEndpoint
    projectPrincipalId = $project.identity.principalId
    agentName = $agentName
    agentVersion = $latest.version
    agentStatus = $latest.status
    agentModel = $latest.definition.model
    agentUpdated = $agentNeedsUpdate
    agentUrl = $agentUrl
    searchServiceName = $searchServiceName
    searchIndexName = $searchIndexName
    knowledgeSourceName = $knowledgeSourceName
    knowledgeBaseName = $knowledgeBaseName
    projectConnectionName = $connectionName
    mcpEndpoint = $mcpEndpoint
    smokeTest = $smokeTest
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
}
$stateDirectory = Split-Path $statePath -Parent
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$state | ConvertTo-Json -Depth 15 | Set-Content -Path $statePath -Encoding utf8
$state | ConvertTo-Json -Depth 15

$script:ArmToken = $null
$script:FoundryToken = $null
$script:SearchAdminKey = $null