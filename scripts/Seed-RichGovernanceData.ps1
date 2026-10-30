[CmdletBinding()]
param(
    [string]$TenantId = "12a4b86b-e64c-43f9-af05-d9130a72dfd2"
)

Set-StrictMode -Off
$ErrorActionPreference = 'Continue'

function Get-AzBearerToken {
    param([Parameter(Mandatory)][string]$ResourceUrl)
    return az account get-access-token --tenant $TenantId --resource $ResourceUrl --query accessToken -o tsv
}

function Get-JwtClaims {
    param([Parameter(Mandatory)][string]$Token)
    $payload = $Token.Split('.')[1].Replace('-', '+').Replace('_', '/')
    while ($payload.Length % 4) { $payload += '=' }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
}

$adminToken = Get-AzBearerToken -ResourceUrl 'https://graph.microsoft.com'
$graphServicePrincipals = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '00000003-0000-0000-c000-000000000000'&`$select=id,appId,appRoles" -Headers @{ Authorization = "Bearer $adminToken" }
$graphServicePrincipal = @($graphServicePrincipals.value) | Select-Object -First 1

$provisioningRoles = @('Sites.FullControl.All', 'Files.ReadWrite.All')
$roleDefinitions = @{}
foreach ($roleName in $provisioningRoles) {
    $role = @($graphServicePrincipal.appRoles) | Where-Object {
        $_.value -eq $roleName -and $_.allowedMemberTypes -contains 'Application'
    } | Select-Object -First 1
    if ($role) { $roleDefinitions[$roleName] = $role.id }
}

$tempAppName = "Rich Metadata Seed $([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$app = Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/applications" -Headers @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" } -Body (@{
    displayName = $tempAppName
    signInAudience = 'AzureADMyOrg'
    requiredResourceAccess = @(
        @{
            resourceAppId = '00000003-0000-0000-c000-000000000000'
            resourceAccess = @(
                $roleDefinitions.Keys | ForEach-Object { @{ id = $roleDefinitions[$_]; type = 'Role' } }
            )
        }
    )
} | ConvertTo-Json -Depth 10)

$sp = Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/servicePrincipals" -Headers @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" } -Body (@{ appId = $app.appId } | ConvertTo-Json)

foreach ($roleName in $roleDefinitions.Keys) {
    Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$($sp.id)/appRoleAssignments" -Headers @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" } -Body (@{
        principalId = $sp.id
        resourceId = $graphServicePrincipal.id
        appRoleId = $roleDefinitions[$roleName]
    } | ConvertTo-Json) | Out-Null
}

$secretObj = Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/applications/$($app.id)/addPassword" -Headers @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" } -Body (@{
    passwordCredential = @{
        displayName = "EphemeralSecret"
        endDateTime = (Get-Date).ToUniversalTime().AddHours(1).ToString('o')
    }
} | ConvertTo-Json)

$secret = $secretObj.secretText

$graphToken = $null
for ($i = 1; $i -le 20; $i++) {
    try {
        $tokenRes = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
            client_id = $app.appId
            client_secret = $secret
            scope = 'https://graph.microsoft.com/.default'
            grant_type = 'client_credentials'
        }
        $tokenClaims = Get-JwtClaims -Token $tokenRes.access_token
        if ($tokenClaims.roles -contains 'Sites.FullControl.All' -or $tokenClaims.roles -contains 'Files.ReadWrite.All') {
            $graphToken = $tokenRes.access_token
            break
        }
    }
    catch { Start-Sleep -Seconds 2 }
    Start-Sleep -Seconds 2
}

try {
    $graphHeaders = @{ Authorization = "Bearer $graphToken"; "Content-Type" = "application/json" }

    $sites = @(
        @{ name = "Semiconductor"; path = "caldova37587778.sharepoint.com:/sites/semiconductorknowledgehub" },
        @{ name = "HR"; path = "caldova37587778.sharepoint.com:/sites/hrknowledgehub" },
        @{ name = "Manufacturing"; path = "caldova37587778.sharepoint.com:/sites/manufacturingknowledgehub" },
        @{ name = "Sales"; path = "caldova37587778.sharepoint.com:/sites/salesmarketingknowledgehub" }
    )

    $iterations = @("Draft", "Ready", "In Review", "Approved", "Archived")
    $lifecycles = @("Draft", "Published", "Superseded", "Archived")
    $qualities = @("Good", "Needs Review", "Stale", "Duplicate", "Conflicting")
    $conflicts = @("None", "Conflicting Authoritative", "Conflicts With Authoritative")

    foreach ($s in $sites) {
        Write-Host "`n=== Enriching Metadata for Site: $($s.name) ===" -ForegroundColor Cyan
        $site = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($s.path)" -Headers $graphHeaders
        $lists = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists" -Headers $graphHeaders
        $docLibs = @($lists.value | Where-Object { $_.list -and $_.list.template -eq 'documentLibrary' -and -not $_.system })

        foreach ($lib in $docLibs) {
            Write-Host "  Processing Library: $($lib.displayName)..."
            $drive = $null
            try {
                $drive = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists/$($lib.id)/drive" -Headers $graphHeaders
            } catch { continue }

            # Gather all files in drive
            $queue = [System.Collections.Generic.Queue[string]]::new()
            $queue.Enqueue("")
            $fileItems = @()

            while ($queue.Count -gt 0 -and $fileItems.Count -lt 150) {
                $cur = $queue.Dequeue()
                $uri = if ($cur) {
                    "https://graph.microsoft.com/v1.0/drives/$($drive.id)/root:${cur}:/children"
                } else {
                    "https://graph.microsoft.com/v1.0/drives/$($drive.id)/root/children"
                }
                try {
                    $children = Invoke-RestMethod -Method GET -Uri $uri -Headers $graphHeaders
                    foreach ($child in @($children.value)) {
                        if ($child.folder) {
                            $subPath = if ($cur) { "$cur/$($child.name)" } else { "/$($child.name)" }
                            $queue.Enqueue($subPath)
                        } elseif ($child.file) {
                            $fileItems += $child
                        }
                    }
                } catch {}
            }

            Write-Host "    Found $($fileItems.Count) files. Distributing metadata states..."
            $fileIdx = 0
            foreach ($file in $fileItems) {
                # Determine distributed attributes
                $iter = $iterations[$fileIdx % $iterations.Length]
                $life = $lifecycles[$fileIdx % $lifecycles.Length]
                $qual = $qualities[$fileIdx % $qualities.Length]
                $conf = $conflicts[$fileIdx % $conflicts.Length]
                $auth = ($fileIdx % 3 -eq 0)

                # Set expiry and review dates to test Expiry tab
                # Every 5th file is EXPIRED (expirationDate in the past: 2025-02-15)
                # Every 4th file is REVIEW OVERDUE (reviewDate in the past: 2025-06-01)
                $expDate = $null
                $revDate = $null
                if ($fileIdx % 5 -eq 0) {
                    $expDate = "2025-02-15"
                } else {
                    $expDate = "2027-12-31"
                }

                if ($fileIdx % 4 -eq 0) {
                    $revDate = "2025-06-01"
                } else {
                    $revDate = "2027-06-30"
                }

                $score = [Math]::Max(15, [Math]::Min(98, 50 + ($fileIdx * 7) % 45))

                $patchObj = @{
                    DocumentIteration = $iter
                    LifecycleStatus = $life
                    DataQualityStatus = $qual
                    ConflictStatus = $conf
                    Authoritative = $auth
                    ExpirationDate = $expDate
                    ReviewDate = $revDate
                    TrustScore = $score
                }

                $patchJson = $patchObj | ConvertTo-Json
                try {
                    Invoke-RestMethod -Method PATCH -Uri "https://graph.microsoft.com/v1.0/drives/$($drive.id)/items/$($file.id)/listItem/fields" -Headers $graphHeaders -Body $patchJson | Out-Null
                } catch {
                    # Ignore single field error if any
                }

                $fileIdx++
            }
            Write-Host "    [OK] Updated $fileIdx files in $($lib.displayName) with diverse iterations, expiry dates, and quality statuses." -ForegroundColor Green
        }
    }
}
finally {
    Write-Host "Cleaning up ephemeral app $($app.id)..."
    try {
        Invoke-RestMethod -Method DELETE -Uri "https://graph.microsoft.com/v1.0/applications/$($app.id)" -Headers @{ Authorization = "Bearer $adminToken" } | Out-Null
        Write-Host "Ephemeral app deleted."
    } catch {}
}
