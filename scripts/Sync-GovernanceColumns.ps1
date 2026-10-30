[CmdletBinding()]
param(
    [string]$TenantId = "12a4b86b-e64c-43f9-af05-d9130a72dfd2",
    [switch]$DryRun
)

<#
.SYNOPSIS
Adds every governance column in config/governance-policy.json that a document library lacks, on all four knowledge sites.

.DESCRIPTION
Creating columns needs Sites.FullControl.All, which the signed-in user token does not carry. The script creates an
ephemeral Entra app with that application role, uses it, and deletes it in a finally block. Columns that already exist
are left alone; a column whose type differs from the policy is reported, not changed. Any failed column is printed and
the script exits with an error after the last library, so a partial sync is never reported as complete.

.PARAMETER DryRun
Lists the columns that would be created without creating them.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$systemLibraries = @('form templates', 'site assets', 'style library', 'agent assets', 'site pages', 'maintenance log library')
$columnTypes = @('text', 'choice', 'dateTime', 'personOrGroup', 'boolean', 'number')
$sites = @(
    @{ name = 'Semiconductor'; path = 'caldova37587778.sharepoint.com:/sites/semiconductorknowledgehub' },
    @{ name = 'HR'; path = 'caldova37587778.sharepoint.com:/sites/hrknowledgehub' },
    @{ name = 'Manufacturing'; path = 'caldova37587778.sharepoint.com:/sites/manufacturingknowledgehub' },
    @{ name = 'Sales'; path = 'caldova37587778.sharepoint.com:/sites/salesmarketingknowledgehub' }
)
$policy = Get-Content -Raw (Join-Path $PSScriptRoot '..\config\governance-policy.json') | ConvertFrom-Json

function Get-AzBearerToken {
    param([Parameter(Mandatory)][string]$ResourceUrl)
    $token = az account get-access-token --tenant $TenantId --resource $ResourceUrl --query accessToken -o tsv
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "Could not acquire access token for $ResourceUrl from Azure CLI."
    }
    return $token
}

function Get-JwtClaims {
    param([Parameter(Mandatory)][string]$Token)
    $payload = $Token.Split('.')[1].Replace('-', '+').Replace('_', '/')
    while ($payload.Length % 4) { $payload += '=' }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
}

function Get-Prop([object]$object, [string]$name) {
    if ($object.PSObject.Properties.Name -contains $name) { return $object.$name }
    return $null
}

function Get-PolicyColumnType([object]$column) {
    return @($columnTypes | Where-Object { $column.PSObject.Properties.Name -contains $_ })[0]
}

function New-ColumnBody([object]$column) {
    $body = [ordered]@{
        name = $column.name
        displayName = $column.displayName
        description = Get-Prop $column 'description'
        indexed = [bool](Get-Prop $column 'indexed')
        enforceUniqueValues = [bool](Get-Prop $column 'enforceUniqueValues')
    }
    if (Get-Prop $column 'required') { $body.required = $true }
    if (Get-Prop $column 'defaultValue') { $body.defaultValue = @{ value = $column.defaultValue } }
    $type = Get-PolicyColumnType $column
    $body[$type] = $column.$type
    return $body
}

function Get-GraphAll {
    param([Parameter(Mandatory)][string]$Url, [Parameter(Mandatory)][hashtable]$Headers)
    $rows = @()
    $next = $Url
    while ($next) {
        $page = Invoke-RestMethod -Method GET -Uri $next -Headers $Headers
        $rows += @($page.value)
        $next = Get-Prop $page '@odata.nextLink'
    }
    return $rows
}

$adminToken = Get-AzBearerToken -ResourceUrl 'https://graph.microsoft.com'
$graphServicePrincipals = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '00000003-0000-0000-c000-000000000000'&`$select=id,appId,appRoles" -Headers @{ Authorization = "Bearer $adminToken" }
$graphServicePrincipal = @($graphServicePrincipals.value) | Select-Object -First 1
$roleDefinitions = @{}
$role = @($graphServicePrincipal.appRoles) | Where-Object { $_.value -eq 'Sites.FullControl.All' -and $_.allowedMemberTypes -contains 'Application' } | Select-Object -First 1
$roleDefinitions['Sites.FullControl.All'] = $role.id

$correlationId = [Guid]::NewGuid().ToString('N').Substring(0, 10)
$app = Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/applications" -Headers @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" } -Body (@{
    displayName = "Ephemeral Governance Column Sync $correlationId"
    signInAudience = 'AzureADMyOrg'
    requiredResourceAccess = @(@{
        resourceAppId = '00000003-0000-0000-c000-000000000000'
        resourceAccess = @($roleDefinitions.Keys | ForEach-Object { @{ id = $roleDefinitions[$_]; type = 'Role' } })
    })
} | ConvertTo-Json -Depth 10)

try {
    $sp = Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/servicePrincipals" -Headers @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" } -Body (@{ appId = $app.appId } | ConvertTo-Json)
    foreach ($roleName in $roleDefinitions.Keys) {
        Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$($sp.id)/appRoleAssignments" -Headers @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" } -Body (@{
            principalId = $sp.id
            resourceId = $graphServicePrincipal.id
            appRoleId = $roleDefinitions[$roleName]
        } | ConvertTo-Json) | Out-Null
    }
    $secretObj = Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/applications/$($app.id)/addPassword" -Headers @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" } -Body (@{
        passwordCredential = @{ displayName = "EphemeralSecret"; endDateTime = (Get-Date).ToUniversalTime().AddHours(1).ToString('o') }
    } | ConvertTo-Json)

    $graphToken = $null
    for ($attempt = 1; $attempt -le 20 -and -not $graphToken; $attempt++) {
        try {
            $tokenRes = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
                client_id = $app.appId
                client_secret = $secretObj.secretText
                scope = 'https://graph.microsoft.com/.default'
                grant_type = 'client_credentials'
            }
            if ((Get-JwtClaims -Token $tokenRes.access_token).roles -contains 'Sites.FullControl.All') {
                $graphToken = $tokenRes.access_token
            }
        }
        catch {
            Write-Host "  waiting for app role propagation (attempt $attempt)..."
        }
        if (-not $graphToken) { Start-Sleep -Seconds 3 }
    }
    if (-not $graphToken) { throw 'Could not acquire a Graph token with Sites.FullControl.All.' }

    $headers = @{ Authorization = "Bearer $graphToken"; "Content-Type" = "application/json" }
    $created = 0
    $present = 0
    $typeMismatch = @()
    $failures = @()

    foreach ($s in $sites) {
        Write-Host "`nSite: $($s.name)" -ForegroundColor Cyan
        $site = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($s.path)" -Headers $headers
        $lists = Get-GraphAll -Url "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists?`$select=id,displayName,list" -Headers $headers
        $libraries = @($lists | Where-Object { $_.list.template -eq 'documentLibrary' -and $_.displayName.ToLower() -notin $systemLibraries })

        foreach ($lib in $libraries) {
            $columnsUrl = "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists/$($lib.id)/columns"
            $existing = @{}
            foreach ($column in (Get-GraphAll -Url $columnsUrl -Headers $headers)) { $existing[$column.name] = $column }
            $missing = @($policy.sharePointColumns | Where-Object { -not $existing.ContainsKey($_.name) })
            Write-Host ("  {0}: {1} policy columns present, {2} missing" -f $lib.displayName, ($policy.sharePointColumns.Count - $missing.Count), $missing.Count)

            foreach ($column in $policy.sharePointColumns) {
                if ($existing.ContainsKey($column.name)) {
                    $present++
                    $type = Get-PolicyColumnType $column
                    if (-not ($existing[$column.name].PSObject.Properties.Name -contains $type)) {
                        $typeMismatch += "$($s.name)/$($lib.displayName)/$($column.name) expected $type"
                    }
                    continue
                }
                if ($DryRun) {
                    Write-Host "    would create $($column.name)"
                    continue
                }
                try {
                    Invoke-RestMethod -Method POST -Uri $columnsUrl -Headers $headers -Body (New-ColumnBody $column | ConvertTo-Json -Depth 10) | Out-Null
                    $created++
                    Write-Host "    created $($column.name)" -ForegroundColor Green
                }
                catch {
                    $detail = if ($_.ErrorDetails) { $_.ErrorDetails.Message } else { $_.Exception.Message }
                    $failures += "$($s.name)/$($lib.displayName)/$($column.name): $detail"
                    Write-Host "    FAILED $($column.name): $detail" -ForegroundColor Red
                }
            }
        }
    }

    Write-Host "`nCreated: $created  Already present: $present  Type mismatches: $($typeMismatch.Count)  Failed: $($failures.Count)"
    foreach ($line in $typeMismatch) { Write-Host "  type mismatch: $line" -ForegroundColor Yellow }
    if ($failures.Count -gt 0) {
        throw "$($failures.Count) column(s) could not be created. See the FAILED lines above."
    }
}
finally {
    if ($app) {
        try {
            Invoke-RestMethod -Method DELETE -Uri "https://graph.microsoft.com/v1.0/applications/$($app.id)" -Headers @{ Authorization = "Bearer $adminToken" } | Out-Null
            Write-Host "Ephemeral app deleted."
        }
        catch {
            Write-Host "Warning: could not delete ephemeral app $($app.id): $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}
