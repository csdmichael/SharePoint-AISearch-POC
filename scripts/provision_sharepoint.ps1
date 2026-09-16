[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\deployment.json'),
    [string]$TenantId,
    [string]$SiteDisplayName,
    [string]$MailNickname,
    [string]$LibraryDisplayName,
    [string]$CorpusPath,
    [string]$StatePath,
    [int]$ExpectedDocuments,
    [switch]$SiteOnly,
    [switch]$PruneMissingDocuments
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
if (-not $PSBoundParameters.ContainsKey('SiteDisplayName')) { $SiteDisplayName = Get-ConfigValue 'sharePoint.siteDisplayName' }
if (-not $PSBoundParameters.ContainsKey('MailNickname')) { $MailNickname = Get-ConfigValue 'sharePoint.mailNickname' }
if (-not $PSBoundParameters.ContainsKey('LibraryDisplayName')) { $LibraryDisplayName = Get-ConfigValue 'sharePoint.productionLibraryName' }
if (-not $PSBoundParameters.ContainsKey('CorpusPath')) {
    $CorpusPath = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.corpus')
}
if (-not $PSBoundParameters.ContainsKey('StatePath')) {
    $StatePath = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.sharePointState')
}
if (-not $PSBoundParameters.ContainsKey('ExpectedDocuments')) { $ExpectedDocuments = Get-ConfigValue 'corpus.expectedDocuments' }
$GraphApiVersion = Get-ConfigValue 'apiVersions.graph'
$ProvisioningApplicationName = Get-ConfigValue 'sharePoint.provisioningApplicationName'
$Categories = @(Get-ConfigValue 'corpus.categories')

function Get-JwtClaims {
    param([Parameter(Mandatory)][string]$Token)

    $payload = $Token.Split('.')[1].Replace('-', '+').Replace('_', '/')
    while ($payload.Length % 4) { $payload += '=' }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) |
        ConvertFrom-Json
}

function Invoke-Graph {
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'POST', 'PATCH', 'PUT', 'DELETE')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [object]$Body,
        [string]$InFile,
        [switch]$AllowNotFound,
        [string]$Token = $script:GraphToken
    )

    $requestUri = if ($Uri.StartsWith('https://')) { $Uri } else { "https://graph.microsoft.com/$GraphApiVersion$Uri" }
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $parameters = @{
                Method  = $Method
                Uri     = $requestUri
                Headers = @{ Authorization = "Bearer $Token" }
            }
            if ($InFile) {
                $parameters.InFile = $InFile
                $parameters.ContentType = 'application/octet-stream'
            }
            elseif ($null -ne $Body) {
                $parameters.Body = $Body | ConvertTo-Json -Depth 20 -Compress
                $parameters.ContentType = 'application/json'
            }
            return Invoke-RestMethod @parameters
        }
        catch {
            $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
            if ($AllowNotFound -and $status -eq 404) { return $null }
            $details = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
            $identityIsPropagating = $status -eq 401 -and $details -match 'Authorization_IdentityNotFound'
            if (($status -eq 429 -or $status -ge 500 -or $identityIsPropagating) -and $attempt -lt 5) {
                [Threading.Thread]::Sleep([Math]::Pow(2, $attempt) * 1000)
                continue
            }
            throw "Microsoft Graph $Method $requestUri failed ($status): $details"
        }
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

function ConvertTo-DrivePath {
    param([Parameter(Mandatory)][string]$RelativePath)

    return (($RelativePath -split '/') | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/'
}

function Ensure-Column {
    param(
        [Parameter(Mandatory)][string]$SiteId,
        [Parameter(Mandatory)][string]$ListId,
        [Parameter(Mandatory)][object[]]$ExistingColumns,
        [Parameter(Mandatory)][hashtable]$Definition
    )

    $existing = @($ExistingColumns) | Where-Object { $_.name -eq $Definition.name } | Select-Object -First 1
    if ($existing) {
        $expectedType = @('text', 'choice', 'dateTime') | Where-Object { $Definition.ContainsKey($_) } | Select-Object -First 1
        if (-not $expectedType -or $existing.PSObject.Properties.Name -notcontains $expectedType) {
            throw "Existing SharePoint column $($Definition.name) does not have expected type $expectedType."
        }
        if ([bool]$existing.enforceUniqueValues -ne [bool]$Definition.enforceUniqueValues) {
            throw "Existing SharePoint column $($Definition.name) has an unexpected uniqueness constraint."
        }
        if ([bool]$existing.indexed -ne [bool]$Definition.indexed) {
            throw "Existing SharePoint column $($Definition.name) has an unexpected indexing setting."
        }
        if ($expectedType -eq 'choice') {
            $expectedChoices = @($Definition.choice.choices | Sort-Object)
            $actualChoices = @($existing.choice.choices | Sort-Object)
            if (@(Compare-Object $expectedChoices $actualChoices).Count) {
                throw "Existing SharePoint column $($Definition.name) has unexpected choices."
            }
        }
        return
    }
    Invoke-Graph -Method POST -Uri "/sites/$SiteId/lists/$ListId/columns" -Body $Definition | Out-Null
}

$script:GraphToken = $null
$script:AdminGraphToken = $null
$provisioningCorrelationId = [Guid]::NewGuid().ToString('N')
$temporaryDisplayName = "$ProvisioningApplicationName $($provisioningCorrelationId.Substring(0, 12))"
$temporaryApplication = $null
$temporaryServicePrincipal = $null
$temporaryRoleAssignmentIds = @()
$passwordCredential = $null
$temporarySecret = $null

try {
$manifest = @()
$resolvedCorpus = $null
if (-not $SiteOnly) {
    $resolvedCorpus = (Resolve-Path $CorpusPath).Path
    $manifestPath = Join-Path $resolvedCorpus 'manifest.json'
    if (-not (Test-Path $manifestPath)) {
        throw "Corpus manifest not found at $manifestPath. Run generate_corpus.py first."
    }
    $manifest = @(Get-Content $manifestPath -Raw | ConvertFrom-Json)
    if ($manifest.Count -ne $ExpectedDocuments) {
        throw "Expected $ExpectedDocuments corpus entries, found $($manifest.Count)."
    }
    $artifactIds = @($manifest.artifact_id)
    $relativePaths = @($manifest.relative_path)
    if (@($artifactIds | Sort-Object -Unique).Count -ne $manifest.Count) {
        throw 'The corpus manifest contains duplicate artifact IDs.'
    }
    if (@($relativePaths | Sort-Object -Unique).Count -ne $manifest.Count) {
        throw 'The corpus manifest contains duplicate relative paths.'
    }
    foreach ($item in $manifest) {
        $localPath = Join-Path $resolvedCorpus ($item.relative_path -replace '/', [IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path $localPath -PathType Leaf)) {
            throw "Corpus preflight failed; missing file: $localPath"
        }
    }
}

$script:AdminGraphToken = Get-AzBearerToken -ResourceUrl 'https://graph.microsoft.com'
$claims = Get-JwtClaims -Token $script:AdminGraphToken
$scopes = @($claims.scp -split ' ')
$requiredScopes = @('Application.ReadWrite.All', 'AppRoleAssignment.ReadWrite.All')
$missingScopes = @($requiredScopes | Where-Object { $scopes -notcontains $_ })
if ($missingScopes.Count) {
    throw "The Azure PowerShell Graph token is missing admin scopes: $($missingScopes -join ', ')."
}

$me = Invoke-Graph -Method GET -Uri '/me?$select=id,displayName,userPrincipalName' -Token $script:AdminGraphToken
$graphServicePrincipals = Invoke-Graph -Method GET -Uri "/servicePrincipals?`$filter=appId eq '00000003-0000-0000-c000-000000000000'&`$select=id,appId,appRoles" -Token $script:AdminGraphToken
$graphServicePrincipal = @($graphServicePrincipals.value) | Select-Object -First 1
if (-not $graphServicePrincipal) { throw 'Microsoft Graph service principal was not found.' }
$provisioningRoles = @('Group.ReadWrite.All', 'Sites.ReadWrite.All', 'Sites.Manage.All', 'Files.ReadWrite.All')
$roleDefinitions = @{}
foreach ($roleName in $provisioningRoles) {
    $role = @($graphServicePrincipal.appRoles) | Where-Object {
        $_.value -eq $roleName -and $_.allowedMemberTypes -contains 'Application'
    } | Select-Object -First 1
    if (-not $role) { throw "Microsoft Graph application role $roleName was not found." }
    $roleDefinitions[$roleName] = $role.id
}

$temporaryApplication = Invoke-Graph -Method POST -Uri '/applications' -Token $script:AdminGraphToken -Body @{
    displayName = $temporaryDisplayName
    signInAudience = 'AzureADMyOrg'
    requiredResourceAccess = @(
        @{
            resourceAppId = '00000003-0000-0000-c000-000000000000'
            resourceAccess = @(
                $provisioningRoles | ForEach-Object { @{ id = $roleDefinitions[$_]; type = 'Role' } }
            )
        }
    )
}
$temporaryServicePrincipal = Invoke-Graph -Method POST -Uri '/servicePrincipals' -Token $script:AdminGraphToken -Body @{
    appId = $temporaryApplication.appId
}
foreach ($roleName in $provisioningRoles) {
    $roleAssignment = Invoke-Graph -Method POST -Uri "/servicePrincipals/$($temporaryServicePrincipal.id)/appRoleAssignments" -Token $script:AdminGraphToken -Body @{
        principalId = $temporaryServicePrincipal.id
        resourceId = $graphServicePrincipal.id
        appRoleId = $roleDefinitions[$roleName]
    }
    $temporaryRoleAssignmentIds += $roleAssignment.id
}
$passwordCredential = Invoke-Graph -Method POST -Uri "/applications/$($temporaryApplication.id)/addPassword" -Token $script:AdminGraphToken -Body @{
    passwordCredential = @{
        displayName = 'Ephemeral SharePoint corpus upload'
        endDateTime = (Get-Date).ToUniversalTime().AddHours(2).ToString('o')
    }
}
$temporarySecret = $passwordCredential.secretText
for ($attempt = 1; $attempt -le 20 -and -not $script:GraphToken; $attempt++) {
    try {
        $tokenResponse = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
            client_id = $temporaryApplication.appId
            client_secret = $temporarySecret
            scope = 'https://graph.microsoft.com/.default'
            grant_type = 'client_credentials'
        }
        $tokenClaims = Get-JwtClaims -Token $tokenResponse.access_token
        $missingRoles = @($provisioningRoles | Where-Object { $tokenClaims.roles -notcontains $_ })
        if (-not $missingRoles.Count) { $script:GraphToken = $tokenResponse.access_token }
    }
    catch {
        if ($attempt -eq 20) { throw }
    }
    if (-not $script:GraphToken) { [Threading.Thread]::Sleep(3000) }
}
if (-not $script:GraphToken) { throw 'The temporary Graph application roles did not propagate in time.' }

$encodedFilter = [Uri]::EscapeDataString("mailNickname eq '$MailNickname'")
$groups = Invoke-Graph -Method GET -Uri "/groups?`$filter=$encodedFilter&`$select=id,displayName,mailNickname"
$group = @($groups.value) | Select-Object -First 1
if (-not $group) {
    Write-Host "Creating private Microsoft 365 group site '$SiteDisplayName'..."
    $userBinding = "https://graph.microsoft.com/v1.0/users/$($me.id)"
    $group = Invoke-Graph -Method POST -Uri '/groups' -Body @{
        displayName         = $SiteDisplayName
        description         = 'Source-grounded semiconductor documents for Azure AI Search and Foundry agents.'
        groupTypes          = @('Unified')
        mailEnabled         = $true
        mailNickname        = $MailNickname
        securityEnabled     = $false
        visibility          = 'Private'
        'owners@odata.bind' = @($userBinding)
        'members@odata.bind' = @($userBinding)
    }
}

$site = $null
for ($attempt = 1; $attempt -le 30 -and -not $site; $attempt++) {
    $site = Invoke-Graph -Method GET -Uri "/groups/$($group.id)/sites/root?`$select=id,displayName,webUrl" -AllowNotFound
    if (-not $site) { [Threading.Thread]::Sleep(5000) }
}
if (-not $site) {
    throw "The SharePoint site for group $($group.id) was not ready after 150 seconds. Rerun this script."
}

$lists = Invoke-Graph -Method GET -Uri "/sites/$($site.id)/lists?`$select=id,displayName,webUrl,list"
$library = @($lists.value) | Where-Object {
    $_.displayName -eq $LibraryDisplayName -and $_.list.template -eq 'documentLibrary'
} | Select-Object -First 1
if (-not $library) {
    Write-Host "Creating document library '$LibraryDisplayName'..."
    $library = Invoke-Graph -Method POST -Uri "/sites/$($site.id)/lists" -Body @{
        displayName = $LibraryDisplayName
        description = 'Generated semiconductor knowledge artifacts grounded in Databricks source data.'
        list        = @{ template = 'documentLibrary' }
    }
}

$columns = Invoke-Graph -Method GET -Uri "/sites/$($site.id)/lists/$($library.id)/columns"
$columnDefinitions = @(
    @{
        name = 'ArtifactId'; displayName = 'Artifact ID'; description = 'Stable generated artifact identifier.'
        enforceUniqueValues = $true; indexed = $true
        text = @{ allowMultipleLines = $false; appendChangesToExistingText = $false; linesForEditing = 1; maxLength = 64 }
    },
    @{
        name = 'KnowledgeCategory'; displayName = 'Knowledge Category'; description = 'Logical retrieval category.'
        enforceUniqueValues = $false; indexed = $true
        choice = @{ allowTextEntry = $false; choices = @('Quality', 'Manufacturing', 'Inventory', 'Sales', 'Supply Chain', 'Yield'); displayAs = 'dropDownMenu' }
    },
    @{
        name = 'SourceTable'; displayName = 'Source Table'; description = 'Fully qualified Databricks source table.'
        enforceUniqueValues = $false; indexed = $true
        text = @{ allowMultipleLines = $false; appendChangesToExistingText = $false; linesForEditing = 1; maxLength = 255 }
    },
    @{
        name = 'SourceSystem'; displayName = 'Source System'; description = 'System used to obtain the source profile.'
        enforceUniqueValues = $false; indexed = $false
        text = @{ allowMultipleLines = $false; appendChangesToExistingText = $false; linesForEditing = 1; maxLength = 255 }
    },
    @{
        name = 'ProfileGeneratedAt'; displayName = 'Profile Generated At'; description = 'UTC timestamp of the source profile.'
        enforceUniqueValues = $false; indexed = $false
        dateTime = @{ displayAs = 'default'; format = 'dateTime' }
    }
)
foreach ($definition in $columnDefinitions) {
    Ensure-Column -SiteId $site.id -ListId $library.id -ExistingColumns @($columns.value) -Definition $definition
}

$drive = Invoke-Graph -Method GET -Uri "/sites/$($site.id)/lists/$($library.id)/drive?`$select=id,name,webUrl"
foreach ($category in $Categories) {
    $encodedCategory = [Uri]::EscapeDataString($category)
    $folder = Invoke-Graph -Method GET -Uri "/drives/$($drive.id)/root:/$encodedCategory" -AllowNotFound
    if (-not $folder) {
        Invoke-Graph -Method POST -Uri "/drives/$($drive.id)/root/children" -Body @{
            name = $category
            folder = @{}
            '@microsoft.graph.conflictBehavior' = 'fail'
        } | Out-Null
    }
}

if ($PruneMissingDocuments -and -not $SiteOnly) {
    $expectedPaths = @{}
    foreach ($item in $manifest) {
        $expectedPaths["$($item.category)/$($item.filename)"] = $true
    }
    foreach ($category in $Categories) {
        $encodedCategory = [Uri]::EscapeDataString($category)
        $children = Invoke-Graph -Method GET -Uri "/drives/$($drive.id)/root:/$encodedCategory`:/children?`$select=id,name,file"
        foreach ($child in @($children.value)) {
            if ($child.file -and -not $expectedPaths.ContainsKey("$category/$($child.name)")) {
                Invoke-Graph -Method DELETE -Uri "/drives/$($drive.id)/items/$($child.id)" | Out-Null
            }
        }
    }
}

$uploadedCount = 0
if (-not $SiteOnly) {
    foreach ($item in $manifest) {
        $localPath = Join-Path $resolvedCorpus ($item.relative_path -replace '/', [IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path $localPath)) { throw "Missing corpus file: $localPath" }
        $drivePath = ConvertTo-DrivePath -RelativePath "$($item.category)/$($item.filename)"
        $uploaded = Invoke-Graph -Method PUT -Uri "/drives/$($drive.id)/root:/$drivePath`:/content" -InFile $localPath
        Invoke-Graph -Method PATCH -Uri "/drives/$($drive.id)/items/$($uploaded.id)/listItem/fields" -Body @{
            Title              = $item.title
            ArtifactId         = $item.artifact_id
            KnowledgeCategory  = $item.category
            SourceTable        = $item.source_table
            SourceSystem       = $item.source_system
            ProfileGeneratedAt = $item.profile_generated_at
        } | Out-Null
        $uploadedCount++
        if ($uploadedCount % 20 -eq 0) { Write-Host "Uploaded $uploadedCount of $($manifest.Count) documents..." }
    }
}

if (-not $SiteOnly) {
    $expectedByPath = @{}
    foreach ($item in $manifest) { $expectedByPath["$($item.category)/$($item.filename)"] = $item }
    $remoteByPath = @{}
    foreach ($category in $Categories) {
        $encodedCategory = [Uri]::EscapeDataString($category)
        $children = Invoke-Graph -Method GET -Uri "/drives/$($drive.id)/root:/$encodedCategory`:/children?`$select=id,name,file"
        foreach ($child in @($children.value)) {
            if ($child.file) { $remoteByPath["$category/$($child.name)"] = $child }
        }
    }
    $pathDifference = @(Compare-Object @($expectedByPath.Keys | Sort-Object) @($remoteByPath.Keys | Sort-Object))
    if ($pathDifference.Count) {
        $differenceText = $pathDifference | ForEach-Object { "$($_.SideIndicator)$($_.InputObject)" }
        throw "SharePoint inventory does not match the manifest: $($differenceText -join ', ')"
    }
    foreach ($remotePath in $expectedByPath.Keys) {
        $expected = $expectedByPath[$remotePath]
        $remote = $remoteByPath[$remotePath]
        $fields = Invoke-Graph -Method GET -Uri "/drives/$($drive.id)/items/$($remote.id)/listItem/fields"
        $metadataMatches = $fields.ArtifactId -eq $expected.artifact_id -and
            $fields.KnowledgeCategory -eq $expected.category -and
            $fields.SourceTable -eq $expected.source_table -and
            $fields.SourceSystem -eq $expected.source_system
        $expectedTimestamp = [DateTimeOffset]::Parse($expected.profile_generated_at)
        $actualTimestamp = [DateTimeOffset]::Parse($fields.ProfileGeneratedAt)
        if (-not $metadataMatches -or [Math]::Abs(($actualTimestamp - $expectedTimestamp).TotalSeconds) -gt 1) {
            throw "SharePoint metadata does not match the manifest for $remotePath."
        }
    }
}

$state = [ordered]@{
    tenantId          = $TenantId
    owner             = $me.userPrincipalName
    groupId           = $group.id
    siteId            = $site.id
    siteUrl           = $site.webUrl
    libraryId         = $library.id
    libraryName       = $LibraryDisplayName
    libraryUrl        = $library.webUrl
    driveId           = $drive.id
    uploadedDocuments = if ($SiteOnly) { 0 } else { $uploadedCount }
    validatedRemoteDocuments = if ($SiteOnly) { 0 } else { $remoteByPath.Count }
    generatedAt       = (Get-Date).ToUniversalTime().ToString('o')
}
$stateDirectory = Split-Path $StatePath -Parent
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$state | ConvertTo-Json -Depth 6 | Set-Content -Path $StatePath -Encoding utf8
$state | ConvertTo-Json -Depth 6
}
finally {
    $cleanupErrors = @()
    if ($script:AdminGraphToken) {
        $correlatedApplications = @()
        try {
            $encodedTemporaryName = [Uri]::EscapeDataString("displayName eq '$temporaryDisplayName'")
            $applicationMatches = Invoke-Graph -Method GET -Uri "/applications?`$filter=$encodedTemporaryName&`$select=id,appId,displayName,passwordCredentials" -Token $script:AdminGraphToken
            $correlatedApplications = @($applicationMatches.value)
        }
        catch { $cleanupErrors += "application discovery ($provisioningCorrelationId): $($_.Exception.Message)" }
        if ($temporaryApplication -and $correlatedApplications.id -notcontains $temporaryApplication.id) {
            $correlatedApplications += $temporaryApplication
        }

        $correlatedAppIds = @()
        foreach ($applicationToRemove in $correlatedApplications) {
            $correlatedAppIds += $applicationToRemove.appId
            $passwords = @($applicationToRemove.passwordCredentials)
            if (-not $passwords.Count) {
                try {
                    $applicationDetails = Invoke-Graph -Method GET -Uri "/applications/$($applicationToRemove.id)?`$select=id,appId,passwordCredentials" -Token $script:AdminGraphToken -AllowNotFound
                    $passwords = @($applicationDetails.passwordCredentials)
                }
                catch { $cleanupErrors += "password discovery $($applicationToRemove.id): $($_.Exception.Message)" }
            }
            foreach ($password in $passwords) {
                try {
                    Invoke-Graph -Method POST -Uri "/applications/$($applicationToRemove.id)/removePassword" -Token $script:AdminGraphToken -Body @{ keyId = $password.keyId } | Out-Null
                }
                catch { $cleanupErrors += "password $($password.keyId): $($_.Exception.Message)" }
            }

            try {
                $encodedAppId = [Uri]::EscapeDataString("appId eq '$($applicationToRemove.appId)'")
                $servicePrincipalMatches = Invoke-Graph -Method GET -Uri "/servicePrincipals?`$filter=$encodedAppId&`$select=id,appId" -Token $script:AdminGraphToken
                foreach ($servicePrincipalToRemove in @($servicePrincipalMatches.value)) {
                    $assignmentsToRemove = Invoke-Graph -Method GET -Uri "/servicePrincipals/$($servicePrincipalToRemove.id)/appRoleAssignments" -Token $script:AdminGraphToken
                    foreach ($assignment in @($assignmentsToRemove.value)) {
                        Invoke-Graph -Method DELETE -Uri "/servicePrincipals/$($servicePrincipalToRemove.id)/appRoleAssignments/$($assignment.id)" -Token $script:AdminGraphToken -AllowNotFound | Out-Null
                    }
                    Invoke-Graph -Method DELETE -Uri "/servicePrincipals/$($servicePrincipalToRemove.id)" -Token $script:AdminGraphToken -AllowNotFound | Out-Null
                }
            }
            catch { $cleanupErrors += "service principals for $($applicationToRemove.appId): $($_.Exception.Message)" }

            try {
                Invoke-Graph -Method DELETE -Uri "/applications/$($applicationToRemove.id)" -Token $script:AdminGraphToken -AllowNotFound | Out-Null
            }
            catch { $cleanupErrors += "application $($applicationToRemove.id): $($_.Exception.Message)" }
        }

        try {
            $encodedTemporaryName = [Uri]::EscapeDataString("displayName eq '$temporaryDisplayName'")
            $remainingApplications = Invoke-Graph -Method GET -Uri "/applications?`$filter=$encodedTemporaryName&`$select=id,appId" -Token $script:AdminGraphToken
            if (@($remainingApplications.value).Count) {
                $cleanupErrors += "$(@($remainingApplications.value).Count) correlated applications still exist"
            }
            foreach ($appId in @($correlatedAppIds | Sort-Object -Unique)) {
                $encodedAppId = [Uri]::EscapeDataString("appId eq '$appId'")
                $remainingServicePrincipals = Invoke-Graph -Method GET -Uri "/servicePrincipals?`$filter=$encodedAppId&`$select=id" -Token $script:AdminGraphToken
                if (@($remainingServicePrincipals.value).Count) {
                    $cleanupErrors += "service principal for $appId still exists"
                }
            }
        }
        catch { $cleanupErrors += "cleanup verification ($provisioningCorrelationId): $($_.Exception.Message)" }
    }
    $temporarySecret = $null
    Remove-Variable GraphToken -Scope Script -ErrorAction SilentlyContinue
    Remove-Variable AdminGraphToken -Scope Script -ErrorAction SilentlyContinue
    if ($cleanupErrors.Count) {
        throw "Temporary Graph provisioner cleanup failed (correlation=$provisioningCorrelationId, displayName='$temporaryDisplayName'): $($cleanupErrors -join ' | ')"
    }
}