<#
.SYNOPSIS
    Discards checkouts that block governance writes in the target document libraries.

.DESCRIPTION
    SharePoint rejects metadata writes (HTTP 423, resourceLocked) on files another principal has checked out. In the
    Trusted Knowledge libraries the holder is the "SharePoint App" system account, which left the .mp4, .pdf, .txt and
    .vtt files checked out. Graph's discardCheckout action returns 423 for delegated callers, but an application token
    with write access can discard any checkout, so this script:
      1. lists the checked-out files in the libraries from governance-targets.json;
      2. skips files checked out by the signed-in user, so no one's own draft is discarded;
      3. discards the other checkouts with a temporary app that holds Files.ReadWrite.All, which is deleted in a
         finally block;
      4. re-reads the libraries and fails if any checkout remains.

    Discarding reverts a checked-out file to its last checked-in version. These files were published (level "published"),
    so the content and version do not change. Use -DryRun to list the checkouts without discarding them.

.PARAMETER TargetsPath
    Library list. Defaults to governance-targets.json beside this script.

.PARAMETER SiteId
    Optional siteId from the targets file to limit the run to one site.

.PARAMETER DryRun
    Lists the checkouts that would be discarded and changes nothing.
#>
[CmdletBinding()]
param(
    [string]$TargetsPath = (Join-Path $PSScriptRoot 'governance-targets.json'),
    [string]$SiteId,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$graphAppId = '00000003-0000-0000-c000-000000000000'
$writeRole = 'Files.ReadWrite.All'
$targets = Get-Content -Raw -Path $TargetsPath | ConvertFrom-Json
$tenantId = [string]$targets.tenantId
$script:UserToken = (az account get-access-token --tenant $tenantId --resource https://graph.microsoft.com --query accessToken -o tsv)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($script:UserToken)) {
    throw 'Could not get a Microsoft Graph token from Azure CLI. Run az login for the tenant and retry.'
}
$script:UserToken = $script:UserToken.Trim()
$script:CreatedAppId = $null

function Get-Prop {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Invoke-Api {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Uri,
        [ValidateSet('GET', 'POST', 'PATCH', 'DELETE')][string]$Method = 'GET',
        $Body = $null,
        [string]$Token = $script:UserToken
    )
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            $parameters = @{
                Method      = $Method
                Uri         = $Uri
                Headers     = @{ Authorization = "Bearer $Token" }
                ErrorAction = 'Stop'
            }
            if ($null -ne $Body) {
                $parameters.Body = ConvertTo-Json -InputObject $Body -Depth 8 -Compress
                $parameters.ContentType = 'application/json'
            }
            $response = Invoke-WebRequest @parameters
            if ([string]::IsNullOrWhiteSpace($response.Content)) { return $null }
            return ($response.Content | ConvertFrom-Json -DateKind String)
        }
        catch {
            $statusCode = 0
            $retryAfter = 0
            if ($_.Exception.Response) {
                $statusCode = [int]$_.Exception.Response.StatusCode
                $headerValues = $null
                if ($_.Exception.Response.Headers.TryGetValues('Retry-After', [ref]$headerValues)) {
                    [void][int]::TryParse([string]@($headerValues)[0], [ref]$retryAfter)
                }
            }
            if (($statusCode -in 429, 500, 502, 503, 504) -and $attempt -lt 6) {
                Start-Sleep -Seconds ([Math]::Max([Math]::Max($retryAfter, 2), [Math]::Pow(2, $attempt)))
                continue
            }
            $detail = if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
            throw "$Method $Uri failed (HTTP $statusCode): $detail"
        }
    }
}

function Get-JwtClaims {
    param([Parameter(Mandatory)][string]$Token)
    $payload = $Token.Split('.')[1].Replace('-', '+').Replace('_', '/')
    switch ($payload.Length % 4) {
        2 { $payload += '==' }
        3 { $payload += '=' }
    }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
}

function New-WriteApp {
    param([string]$Stamp)
    $graphServicePrincipal = @((Invoke-Api -Uri "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '$graphAppId'&`$select=id,appId,appRoles").value)[0]
    $roles = @($graphServicePrincipal.appRoles | Where-Object { $_.value -eq $writeRole -and $_.allowedMemberTypes -contains 'Application' })
    if ($roles.Count -ne 1) { throw "Microsoft Graph application role $writeRole was not found." }
    $app = Invoke-Api -Method POST -Uri 'https://graph.microsoft.com/v1.0/applications' -Body @{
        displayName            = "Governance Checkout Release $Stamp"
        signInAudience         = 'AzureADMyOrg'
        requiredResourceAccess = @(@{ resourceAppId = $graphAppId; resourceAccess = @(@{ id = $roles[0].id; type = 'Role' }) })
    }
    $script:CreatedAppId = [string]$app.id
    $servicePrincipal = Invoke-Api -Method POST -Uri 'https://graph.microsoft.com/v1.0/servicePrincipals' -Body @{ appId = $app.appId }
    Invoke-Api -Method POST -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$($servicePrincipal.id)/appRoleAssignments" -Body @{
        principalId = $servicePrincipal.id
        resourceId  = $graphServicePrincipal.id
        appRoleId   = $roles[0].id
    } | Out-Null
    $password = Invoke-Api -Method POST -Uri "https://graph.microsoft.com/v1.0/applications/$($app.id)/addPassword" -Body @{
        passwordCredential = @{ displayName = 'run'; endDateTime = (Get-Date).ToUniversalTime().AddHours(2).ToString('o') }
    }
    return [pscustomobject]@{ ClientId = $app.appId; Secret = $password.secretText }
}

function Get-WriteToken {
    param($App)
    $lastResult = 'no response'
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $response = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/token" -Body @{
                client_id     = $App.ClientId
                client_secret = $App.Secret
                scope         = 'https://graph.microsoft.com/.default'
                grant_type    = 'client_credentials'
            }
            $roles = @((Get-JwtClaims -Token $response.access_token).roles)
            if ($roles -contains $writeRole) { return $response.access_token }
            $lastResult = "token roles were $($roles -join ', ')"
        }
        catch { $lastResult = $_.Exception.Message }
        Start-Sleep -Seconds 4
    }
    throw "The write app token did not receive $writeRole in time. Last result: $lastResult"
}

function Get-LibraryId {
    param([string]$SiteGraphId, [string]$LibraryName)
    $lists = @((Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$SiteGraphId/lists?`$select=id,displayName,name,list&`$top=200").value)
    $found = @($lists | Where-Object { $_.displayName -eq $LibraryName -and (Get-Prop $_.list 'template') -eq 'documentLibrary' })
    if ($found.Count -ne 1) { throw "Expected exactly one document library named '$LibraryName' in site $SiteGraphId; found $($found.Count)." }
    return [string]$found[0].id
}

function Get-LibraryRows {
    param([string]$SiteGraphId, [string]$ListId)
    $rows = [System.Collections.Generic.List[object]]::new()
    $next = "https://graph.microsoft.com/v1.0/sites/$SiteGraphId/lists/$ListId/items?`$expand=fields&`$top=999"
    while ($next) {
        $page = Invoke-Api -Uri $next
        foreach ($row in @($page.value)) { $rows.Add($row) }
        $next = Get-Prop $page '@odata.nextLink'
    }
    return $rows
}

$me = Invoke-Api -Uri 'https://graph.microsoft.com/v1.0/me?$select=id,displayName,userPrincipalName'
$candidates = [System.Collections.Generic.List[object]]::new()
$selectedSites = @($targets.sites | Where-Object { -not $SiteId -or $_.siteId -eq $SiteId })
foreach ($site in $selectedSites) {
    $siteGraphId = [string](Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$($site.graphPath)").id
    $signedInLookup = $null
    $userInfo = @((Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$siteGraphId/lists/User%20Information%20List/items?`$expand=fields&`$top=999").value)
    foreach ($entry in $userInfo) {
        $login = [string](Get-Prop (Get-Prop $entry 'fields') 'EMail')
        $claim = [string](Get-Prop (Get-Prop $entry 'fields') 'Name')
        if ($login -ieq $me.userPrincipalName -or $claim -like "*|$($me.userPrincipalName)") { $signedInLookup = [string]$entry.id; break }
    }
    foreach ($libraryName in @($site.libraries)) {
        $listId = Get-LibraryId -SiteGraphId $siteGraphId -LibraryName $libraryName
        $driveId = [string](Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$siteGraphId/lists/$listId/drive").id
        $rows = Get-LibraryRows -SiteGraphId $siteGraphId -ListId $listId
        $checked = @($rows | Where-Object { [string](Get-Prop (Get-Prop $_ 'fields') 'CheckoutUserLookupId') -ne '' })
        $mine = @($checked | Where-Object { [string](Get-Prop (Get-Prop $_ 'fields') 'CheckoutUserLookupId') -eq $signedInLookup })
        Write-Host "== $($site.siteId) / $libraryName : $($checked.Count) checked out ($($mine.Count) by the signed-in user, kept)"
        foreach ($row in @($checked | Where-Object { [string](Get-Prop (Get-Prop $_ 'fields') 'CheckoutUserLookupId') -ne $signedInLookup })) {
            $driveItem = Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$siteGraphId/lists/$listId/items/$($row.id)/driveItem"
            $candidates.Add([pscustomobject]@{
                    Site = $site.siteId; Library = $libraryName; Name = [string](Get-Prop $row.fields 'FileLeafRef')
                    SiteGraphId = $siteGraphId; ListId = $listId; ItemId = [string]$row.id
                    DriveId = [string]$driveItem.parentReference.driveId; DriveItemId = [string]$driveItem.id
                    Holder = [string](Get-Prop $row.fields 'CheckoutUserLookupId')
                })
        }
    }
}
Write-Host "Checkouts to discard: $($candidates.Count)"
if ($candidates.Count -eq 0 -or $DryRun) {
    if ($DryRun) { $candidates | Group-Object Site, Library | ForEach-Object { Write-Host "  $($_.Name): $($_.Count)" } }
    return
}

$stamp = Get-Date -Format 'yyyyMMddHHmmss'
try {
    $app = New-WriteApp -Stamp $stamp
    $writeToken = Get-WriteToken -App $app
    $failures = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in $candidates) {
        try {
            Invoke-Api -Method POST -Token $writeToken -Uri "https://graph.microsoft.com/v1.0/drives/$($candidate.DriveId)/items/$($candidate.DriveItemId)/discardCheckout" | Out-Null
        }
        catch { $failures.Add("$($candidate.Site)/$($candidate.Library) '$($candidate.Name)': $($_.Exception.Message)") }
    }
    Write-Host "Discard requests: $($candidates.Count - $failures.Count) succeeded, $($failures.Count) failed."
    $remaining = 0
    foreach ($site in $selectedSites) {
        $siteGraphId = [string](Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$($site.graphPath)").id
        foreach ($libraryName in @($site.libraries)) {
            $listId = Get-LibraryId -SiteGraphId $siteGraphId -LibraryName $libraryName
            $remaining += @(Get-LibraryRows -SiteGraphId $siteGraphId -ListId $listId | Where-Object {
                    [string](Get-Prop (Get-Prop $_ 'fields') 'CheckoutUserLookupId') -ne '' }).Count
        }
    }
    Write-Host "Checkouts remaining in the target libraries (including the signed-in user's): $remaining"
    if ($failures.Count -gt 0) {
        foreach ($failure in $failures) { Write-Host "FAILED: $failure" -ForegroundColor Red }
        throw "$($failures.Count) discard request(s) failed."
    }
}
finally {
    if ($script:CreatedAppId) {
        try {
            Invoke-Api -Method DELETE -Uri "https://graph.microsoft.com/v1.0/applications/$($script:CreatedAppId)" | Out-Null
            Write-Host 'Deleted the temporary write app.'
        }
        catch {
            Write-Warning "Could not delete temporary app $($script:CreatedAppId): $($_.Exception.Message)"
        }
    }
}
