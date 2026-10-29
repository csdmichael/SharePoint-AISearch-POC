[CmdletBinding()]
param(
    [string]$TenantId = "12a4b86b-e64c-43f9-af05-d9130a72dfd2"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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

$adminToken = Get-AzBearerToken -ResourceUrl 'https://graph.microsoft.com'
$graphServicePrincipals = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '00000003-0000-0000-c000-000000000000'&`$select=id,appId,appRoles" -Headers @{ Authorization = "Bearer $adminToken" }
$graphServicePrincipal = @($graphServicePrincipals.value) | Select-Object -First 1

$provisioningRoles = @('Group.ReadWrite.All', 'Sites.FullControl.All', 'Sites.Manage.All', 'Sites.ReadWrite.All', 'Files.ReadWrite.All')
$roleDefinitions = @{}
foreach ($roleName in $provisioningRoles) {
    $role = @($graphServicePrincipal.appRoles) | Where-Object {
        $_.value -eq $roleName -and $_.allowedMemberTypes -contains 'Application'
    } | Select-Object -First 1
    if ($role) {
        $roleDefinitions[$roleName] = $role.id
    }
}

$correlationId = [Guid]::NewGuid().ToString('N').Substring(0, 10)
$tempAppName = "Ephemeral Column Provisioner $correlationId"
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

$sp = Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/servicePrincipals" -Headers @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" } -Body (@{
    appId = $app.appId
} | ConvertTo-Json)

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
Write-Host "Created ephemeral service principal $($sp.id) for column provisioning."

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
        if ($tokenClaims.roles -contains 'Sites.Manage.All' -or $tokenClaims.roles -contains 'Sites.FullControl.All') {
            $graphToken = $tokenRes.access_token
            Write-Host "Acquired app token with required SharePoint roles."
            break
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
    Start-Sleep -Seconds 2
}

if (-not $graphToken) {
    throw "Could not acquire Graph token with required roles."
}

try {
    $graphHeaders = @{ Authorization = "Bearer $graphToken"; "Content-Type" = "application/json" }
    
    $sites = @(
        @{ name = "Semiconductor"; path = "caldova37587778.sharepoint.com:/sites/semiconductorknowledgehub" },
        @{ name = "HR"; path = "caldova37587778.sharepoint.com:/sites/hrknowledgehub" },
        @{ name = "Manufacturing"; path = "caldova37587778.sharepoint.com:/sites/manufacturingknowledgehub" },
        @{ name = "Sales"; path = "caldova37587778.sharepoint.com:/sites/salesmarketingknowledgehub" }
    )

    $columnDefinition = @{
        description = "Required document iteration state (Draft, Ready, etc.) for upload and revision workflows."
        displayName = "Document Iteration"
        name = "DocumentIteration"
        enforceUniqueValues = $false
        indexed = $true
        required = $true
        choice = @{
            allowTextEntry = $false
            choices = @("Draft", "Ready", "In Review", "Approved", "Archived")
            displayAs = "dropDownMenu"
        }
        defaultValue = @{
            value = "Draft"
        }
    } | ConvertTo-Json -Depth 10

    foreach ($s in $sites) {
        Write-Host "`nProcessing Site: $($s.name) ($($s.path))..." -ForegroundColor Cyan
        $site = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($s.path)" -Headers $graphHeaders
        $lists = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists" -Headers $graphHeaders
        $docLibs = @($lists.value | Where-Object { 
            $_.PSObject.Properties.Name -contains 'list' -and 
            $null -ne $_.list -and 
            $_.list.template -eq 'documentLibrary' -and 
            (-not ($_.PSObject.Properties.Name -contains 'system' -and $_.system))
        })
        
        foreach ($lib in $docLibs) {
            Write-Host "  Checking Library: $($lib.displayName) (ID: $($lib.id))..."
            $cols = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists/$($lib.id)/columns" -Headers $graphHeaders
            $existing = @($cols.value | Where-Object { $_.name -eq 'DocumentIteration' }) | Select-Object -First 1
            if (-not $existing) {
                Write-Host "    Adding DocumentIteration column..." -ForegroundColor Yellow
                $newCol = Invoke-RestMethod -Method POST -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists/$($lib.id)/columns" -Headers $graphHeaders -Body $columnDefinition
                $isRequired = if ($newCol.PSObject.Properties.Name -contains 'required') { $newCol.required } else { $true }
                Write-Host "    [OK] Column created: $($newCol.name) (Required: $isRequired)" -ForegroundColor Green
            } else {
                Write-Host "    [OK] DocumentIteration column already present." -ForegroundColor Green
            }

            # Update existing documents in the library to have DocumentIteration populated
            try {
                $drive = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists/$($lib.id)/drive" -Headers $graphHeaders
            } catch {
                Write-Host "    No drive for library: $($lib.displayName)"
                continue
            }
            
            # Helper to recursively inspect and set fields on files
            $pendingFolders = [System.Collections.Generic.Queue[string]]::new()
            $pendingFolders.Enqueue("")
            $updatedFiles = 0

            while ($pendingFolders.Count -gt 0) {
                $cur = $pendingFolders.Dequeue()
                $uri = if ($cur) {
                    "https://graph.microsoft.com/v1.0/drives/$($drive.id)/root:${cur}:/children?`$expand=listItem"
                } else {
                    "https://graph.microsoft.com/v1.0/drives/$($drive.id)/root/children?`$expand=listItem"
                }
                
                try {
                    $childrenRes = Invoke-RestMethod -Method GET -Uri $uri -Headers $graphHeaders
                    foreach ($child in @($childrenRes.value)) {
                        $isFolder = $child.PSObject.Properties.Name -contains 'folder' -and $null -ne $child.folder
                        $isFile = $child.PSObject.Properties.Name -contains 'file' -and $null -ne $child.file
                        $hasListItem = $child.PSObject.Properties.Name -contains 'listItem' -and $null -ne $child.listItem

                        if ($isFolder) {
                            $nextPath = if ($cur) { "$cur/$($child.name)" } else { "/$($child.name)" }
                            $pendingFolders.Enqueue($nextPath)
                        } elseif ($isFile -and $hasListItem) {
                            $itemId = $child.id
                            $fields = if ($child.listItem.PSObject.Properties.Name -contains 'fields') { $child.listItem.fields } else { $null }
                            $curIteration = if ($fields -and $fields.PSObject.Properties.Name -contains 'DocumentIteration') { $fields.DocumentIteration } else { $null }
                            if ([string]::IsNullOrWhiteSpace($curIteration)) {
                                # Determine value: if LifecycleStatus is Draft or name has draft -> Draft, else Ready
                                $val = "Ready"
                                $hasLifecycle = $fields -and ($fields.PSObject.Properties.Name -contains 'LifecycleStatus')
                                if ($child.name -match 'draft' -or ($hasLifecycle -and $fields.LifecycleStatus -eq 'Draft')) {
                                    $val = "Draft"
                                }
                                $patchBody = @{ DocumentIteration = $val } | ConvertTo-Json
                                Invoke-RestMethod -Method PATCH -Uri "https://graph.microsoft.com/v1.0/drives/$($drive.id)/items/$itemId/listItem/fields" -Headers $graphHeaders -Body $patchBody | Out-Null
                                $updatedFiles++
                            }
                        }
                    }
                } catch {
                    Write-Host "    Warning reading children at $($cur): $($_.Exception.Message)" -ForegroundColor DarkYellow
                }
            }
            if ($updatedFiles -gt 0) {
                Write-Host "    Updated $updatedFiles existing document(s) with DocumentIteration." -ForegroundColor Green
            }
        }
    }
    Write-Host "`nAll libraries across all sites have been updated with the required DocumentIteration column." -ForegroundColor Green
}
finally {
    Write-Host "Cleaning up ephemeral app $($app.id)..."
    try {
        Invoke-RestMethod -Method DELETE -Uri "https://graph.microsoft.com/v1.0/applications/$($app.id)" -Headers @{ Authorization = "Bearer $adminToken" } | Out-Null
        Write-Host "Ephemeral app deleted."
    } catch {
        Write-Host "Warning cleaning up app: $($_.Exception.Message)"
    }
}
