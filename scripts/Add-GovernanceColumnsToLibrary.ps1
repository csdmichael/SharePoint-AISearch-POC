<#
.SYNOPSIS
    Ensures a SharePoint document library exists and carries every governance column defined in
    config/governance-policy.json.

.DESCRIPTION
    Used to extend libraries that did not originate from the governed site template (for
    example the default "Documents" library, or a new library created to hold meeting recordings)
    so they can carry the same 27 governance metadata columns and be seeded/audited the same way.
    Existing columns are left untouched; only missing columns are added.

    Creating a list, and adding columns to a list, both require the Sites.Manage.All application
    role, which the delegated Azure CLI token used elsewhere in these scripts does not carry. This
    script creates a short-lived app registration with that role, uses it for every write, and
    deletes it again before exiting.

.PARAMETER SiteGraphPath
    Microsoft Graph site path, e.g. "contoso.sharepoint.com:/sites/hrknowledgehub".

.PARAMETER LibraryName
    Display name of the target document library, e.g. "Documents" or "Meeting Recordings and Transcripts".

.PARAMETER CreateIfMissing
    Create the document library if a library with this display name does not already exist.

.EXAMPLE
    .\scripts\Add-GovernanceColumnsToLibrary.ps1 -SiteGraphPath "caldova37587778.sharepoint.com:/sites/hrknowledgehub" -LibraryName 'Documents'
#>
[CmdletBinding()]
param(
    [string]$TenantId = (Get-Content -Raw (Join-Path $PSScriptRoot 'governance-targets.json') | ConvertFrom-Json).tenantId,
    [Parameter(Mandatory)][string]$SiteGraphPath,
    [Parameter(Mandatory)][string]$LibraryName,
    [string]$PolicyPath = (Join-Path $PSScriptRoot '..\config\governance-policy.json'),
    [switch]$CreateIfMissing
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:GraphToken = (az account get-access-token --tenant $TenantId --resource https://graph.microsoft.com --query accessToken -o tsv)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($script:GraphToken)) {
    throw 'Could not get a Microsoft Graph token from Azure CLI. Run az login for the tenant and retry.'
}
$script:GraphToken = $script:GraphToken.Trim()

function Get-Prop {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Invoke-Graph {
    param(
        [ValidateSet('GET', 'POST', 'DELETE')][string]$Method = 'GET',
        [Parameter(Mandatory)][string]$Uri,
        $Body = $null,
        [switch]$AllowConflict,
        [string]$BearerToken = $script:GraphToken
    )
    $requestUri = if ($Uri.StartsWith('https://')) { $Uri } else { "https://graph.microsoft.com/v1.0$Uri" }
    $authHeaderValue = 'Bearer ' + $BearerToken
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            $parameters = @{ Method = $Method; Uri = $requestUri; Headers = @{ Authorization = $authHeaderValue } }
            if ($null -ne $Body) {
                $parameters.Body = ConvertTo-Json -InputObject $Body -Depth 10 -Compress
                $parameters.ContentType = 'application/json'
            }
            $response = Invoke-WebRequest @parameters -ErrorAction Stop
            if ([string]::IsNullOrWhiteSpace($response.Content)) { return $null }
            return ($response.Content | ConvertFrom-Json)
        }
        catch {
            $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
            if ($AllowConflict -and $status -in 404, 409) { return $null }
            if (($status -eq 429 -or $status -ge 500) -and $attempt -lt 6) {
                Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
                continue
            }
            $detail = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
            throw "Graph $Method $requestUri failed (HTTP $status): $detail"
        }
    }
}

function New-EphemeralListManagementToken {
    # The delegated Azure CLI token can read/write existing lists, items and file content, but
    # creating a list or adding a column to one requires the Sites.Manage.All application role.
    # Create a short-lived app registration with that role (mirrors provision_sharepoint.ps1),
    # use it once, then delete it from the caller's finally block.
    $servicePrincipals = Invoke-Graph -Uri "/servicePrincipals?`$filter=appId eq '00000003-0000-0000-c000-000000000000'&`$select=id,appId,appRoles"
    $graphSp = @($servicePrincipals.value) | Select-Object -First 1
    if (-not $graphSp) { throw 'Microsoft Graph service principal was not found.' }
    $roleName = 'Sites.Manage.All'
    $role = @($graphSp.appRoles) | Where-Object { $_.value -eq $roleName -and $_.allowedMemberTypes -contains 'Application' } | Select-Object -First 1
    if (-not $role) { throw "Application role $roleName was not found." }

    $displayName = "Ephemeral list management $(([Guid]::NewGuid().ToString('N')).Substring(0, 12))"
    $application = Invoke-Graph -Method POST -Uri '/applications' -Body @{
        displayName            = $displayName
        signInAudience          = 'AzureADMyOrg'
        requiredResourceAccess  = @(@{ resourceAppId = '00000003-0000-0000-c000-000000000000'; resourceAccess = @(@{ id = $role.id; type = 'Role' }) })
    }
    $servicePrincipal = Invoke-Graph -Method POST -Uri '/servicePrincipals' -Body @{ appId = $application.appId }
    Invoke-Graph -Method POST -Uri "/servicePrincipals/$($servicePrincipal.id)/appRoleAssignments" -Body @{
        principalId = $servicePrincipal.id; resourceId = $graphSp.id; appRoleId = $role.id
    } | Out-Null
    $passwordCredential = Invoke-Graph -Method POST -Uri "/applications/$($application.id)/addPassword" -Body @{
        passwordCredential = @{ displayName = 'ephemeral'; endDateTime = (Get-Date).ToUniversalTime().AddHours(1).ToString('o') }
    }
    $secret = $passwordCredential.secretText
    $elevatedToken = $null
    for ($attempt = 1; $attempt -le 20 -and -not $elevatedToken; $attempt++) {
        try {
            $tokenResponse = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
                client_id = $application.appId; client_secret = $secret; scope = 'https://graph.microsoft.com/.default'; grant_type = 'client_credentials'
            }
            $claimsPayload = $tokenResponse.access_token.Split('.')[1].Replace('-', '+').Replace('_', '/')
            while ($claimsPayload.Length % 4) { $claimsPayload += '=' }
            $claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($claimsPayload)) | ConvertFrom-Json
            if ($claims.roles -contains $roleName) { $elevatedToken = $tokenResponse.access_token }
        }
        catch {
            if ($attempt -eq 20) { throw }
        }
        if (-not $elevatedToken) { Start-Sleep -Seconds 3 }
    }
    if (-not $elevatedToken) { throw 'The temporary application role did not propagate in time.' }
    return [pscustomobject]@{
        BearerToken        = $elevatedToken
        ApplicationId      = $application.id
        ServicePrincipalId = $servicePrincipal.id
    }
}

$policy = Get-Content -Raw -Path $PolicyPath | ConvertFrom-Json

Write-Host "Resolving site '$SiteGraphPath'..."
$site = Invoke-Graph -Uri "/sites/$SiteGraphPath"
$lists = Invoke-Graph -Uri "/sites/$($site.id)/lists?`$select=id,displayName,list"
$library = @($lists.value | Where-Object { $_.displayName -eq $LibraryName -and (Get-Prop $_.list 'template') -eq 'documentLibrary' }) | Select-Object -First 1

if (-not $library -and -not $CreateIfMissing) {
    throw "Document library '$LibraryName' not found on site $SiteGraphPath. Pass -CreateIfMissing to create it."
}

Write-Host 'Acquiring a temporary elevated token for list/column management...'
$ephemeral = New-EphemeralListManagementToken
try {
    if (-not $library) {
        Write-Host "Creating document library '$LibraryName'..."
        $library = Invoke-Graph -Method POST -Uri "/sites/$($site.id)/lists" -BearerToken $ephemeral.BearerToken -Body @{
            displayName = $LibraryName
            list        = @{ template = 'documentLibrary' }
        }
        Write-Host "Created document library '$LibraryName' (list id $($library.id))."
    }
    else {
        Write-Host "Found existing library '$LibraryName' (list id $($library.id))."
    }

    $existingColumns = @((Invoke-Graph -Uri "/sites/$($site.id)/lists/$($library.id)/columns?`$select=name").value.name)
    $added = 0
    foreach ($column in $policy.sharePointColumns) {
        if ($existingColumns -contains $column.name) { continue }
        $body = @{
            name                = $column.name
            displayName         = $column.displayName
            description         = $column.description
            indexed             = [bool]$column.indexed
            enforceUniqueValues = [bool]$column.enforceUniqueValues
        }
        foreach ($facet in @('text', 'choice', 'dateTime', 'boolean', 'number', 'personOrGroup')) {
            $value = Get-Prop $column $facet
            if ($null -ne $value) { $body[$facet] = $value }
        }
        Invoke-Graph -Method POST -Uri "/sites/$($site.id)/lists/$($library.id)/columns" -BearerToken $ephemeral.BearerToken -Body $body -AllowConflict | Out-Null
        $added++
        Write-Host "  added column: $($column.name)"
    }
    Write-Host "Done. $added column(s) added; $($existingColumns.Count) already present."
}
finally {
    try { Invoke-Graph -Method DELETE -Uri "/servicePrincipals/$($ephemeral.ServicePrincipalId)" -AllowConflict | Out-Null } catch {}
    try { Invoke-Graph -Method DELETE -Uri "/applications/$($ephemeral.ApplicationId)" -AllowConflict | Out-Null } catch {}
    Write-Host 'Temporary elevated app cleaned up.'
}
