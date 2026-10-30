[CmdletBinding()]
param(
    [string]$TenantId = "12a4b86b-e64c-43f9-af05-d9130a72dfd2"
)

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

$tempAppName = "Upload Duplicates $([Guid]::NewGuid().ToString('N').Substring(0, 8))"
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
    $graphHeaders = @{ Authorization = "Bearer $graphToken" }
    $site = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/caldova37587778.sharepoint.com:/sites/semiconductorknowledgehub" -Headers $graphHeaders
    $library = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists/e96140d6-874b-4dc4-b31b-ae5b0f9e4042" -Headers $graphHeaders
    $drive = Invoke-RestMethod -Method GET -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists/$($library.id)/drive" -Headers $graphHeaders

    # Upload pairs of exact duplicates for DOCX, PPTX, XLSX, and PDF into Quality and Yield
    $duplicatePairs = @(
        @{
            sourceLocalPath = "data\sites\hr\Engineering\Operations\hr_docx_14.docx"
            folder = "Quality"
            canonicalName = "sem-101-standard-operating-procedure-fab.docx"
            duplicateName = "sem-101-standard-operating-procedure-fab-copy.docx"
            canonicalArtifact = "SEM-CAN-101"
            duplicateArtifact = "SEM-DUP-101"
            title = "Standard Operating Procedure: Fab Operations"
        },
        @{
            sourceLocalPath = "data\sites\hr\Engineering\Operations\hr_pptx_14.pptx"
            folder = "Quality"
            canonicalName = "sem-102-executive-presentation-overview.pptx"
            duplicateName = "sem-102-executive-presentation-overview-copy.pptx"
            canonicalArtifact = "SEM-CAN-102"
            duplicateArtifact = "SEM-DUP-102"
            title = "Executive Presentation: Semiconductor Roadmap"
        },
        @{
            sourceLocalPath = "data\sites\hr\Engineering\Operations\hr_xlsx_14.xlsx"
            folder = "Quality"
            canonicalName = "sem-103-financial-and-capacity-workbook.xlsx"
            duplicateName = "sem-103-financial-and-capacity-workbook-copy.xlsx"
            canonicalArtifact = "SEM-CAN-103"
            duplicateArtifact = "SEM-DUP-103"
            title = "Financial and Capacity Planning Workbook"
        },
        @{
            sourceLocalPath = "data\sites\hr\Engineering\Operations\hr_pdf_14.pdf"
            folder = "Yield"
            canonicalName = "sem-104-quality-inspection-certificate.pdf"
            duplicateName = "sem-104-quality-inspection-certificate-copy.pdf"
            canonicalArtifact = "SEM-CAN-104"
            duplicateArtifact = "SEM-DUP-104"
            title = "Quality Inspection Compliance Certificate"
        }
    )

    foreach ($pair in $duplicatePairs) {
        $localPath = Resolve-Path $pair.sourceLocalPath
        $folder = $pair.folder

        # 1. Upload Canonical file
        Write-Host "Uploading Canonical: $($pair.canonicalName)..."
        $uploadUri1 = "https://graph.microsoft.com/v1.0/drives/$($drive.id)/root:/$folder/$($pair.canonicalName)`:/content"
        $up1 = Invoke-RestMethod -Method PUT -Uri $uploadUri1 -Headers @{ Authorization = "Bearer $graphToken"; "Content-Type" = "application/octet-stream" } -InFile $localPath
        $patch1 = @{
            Title = $pair.title
            ArtifactId = $pair.canonicalArtifact
            KnowledgeCategory = "Quality"
            SourceTable = "corp.semiconductor.knowledge_assets"
            SourceSystem = "SharePoint Online"
            LifecycleStatus = "Published"
            DocumentIteration = "Ready"
            Authoritative = $true
            ProfileGeneratedAt = (Get-Date).ToUniversalTime().ToString('o')
        } | ConvertTo-Json
        try {
            Invoke-RestMethod -Method PATCH -Uri "https://graph.microsoft.com/v1.0/drives/$($drive.id)/items/$($up1.id)/listItem/fields" -Headers @{ Authorization = "Bearer $graphToken"; "Content-Type" = "application/json" } -Body $patch1 | Out-Null
            Write-Host "  [OK] Canonical uploaded and tagged (Published, Ready)." -ForegroundColor Green
        } catch {
            Write-Host "  Patch 1 Error: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }

        # 2. Upload Duplicate file (same content, draft iteration)
        Write-Host "Uploading Duplicate: $($pair.duplicateName)..."
        $uploadUri2 = "https://graph.microsoft.com/v1.0/drives/$($drive.id)/root:/$folder/$($pair.duplicateName)`:/content"
        $up2 = Invoke-RestMethod -Method PUT -Uri $uploadUri2 -Headers @{ Authorization = "Bearer $graphToken"; "Content-Type" = "application/octet-stream" } -InFile $localPath
        $patch2 = @{
            Title = "COPY OF: $($pair.title)"
            ArtifactId = $pair.duplicateArtifact
            KnowledgeCategory = "Quality"
            SourceTable = "corp.semiconductor.knowledge_assets"
            SourceSystem = "SharePoint Online"
            LifecycleStatus = "Draft"
            DocumentIteration = "Draft"
            Authoritative = $false
            DuplicateOf = $pair.canonicalName
            ProfileGeneratedAt = (Get-Date).ToUniversalTime().ToString('o')
        } | ConvertTo-Json
        try {
            Invoke-RestMethod -Method PATCH -Uri "https://graph.microsoft.com/v1.0/drives/$($drive.id)/items/$($up2.id)/listItem/fields" -Headers @{ Authorization = "Bearer $graphToken"; "Content-Type" = "application/json" } -Body $patch2 | Out-Null
            Write-Host "  [OK] Duplicate uploaded and tagged (Draft, DuplicateOf=$($pair.canonicalName))." -ForegroundColor Green
        } catch {
            Write-Host "  Patch 2 Error: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }
    }
}
finally {
    Invoke-RestMethod -Method DELETE -Uri "https://graph.microsoft.com/v1.0/applications/$($app.id)" -Headers @{ Authorization = "Bearer $adminToken" } | Out-Null
}
