<#
.SYNOPSIS
    Uploads a generated site corpus (manifest.json + files) into an existing SharePoint
    document library, and optionally removes files that are no longer part of the corpus.

.DESCRIPTION
    Unlike provision_sharepoint.ps1 (which creates a brand new Microsoft 365 group/site for the
    semiconductor POC), this script targets a SharePoint site and document library that already
    exist, so it does not touch site/group provisioning or column schema. It only creates the
    folders the manifest needs and uploads/replaces file content.

.PARAMETER TenantId
    Azure AD tenant ID. Defaults to the tenant in governance-targets.json.

.PARAMETER SiteGraphPath
    Microsoft Graph site path, e.g. "contoso.sharepoint.com:/sites/hrknowledgehub".

.PARAMETER LibraryName
    Display name of the target document library, e.g. "Trusted Knowledge".

.PARAMETER CorpusPath
    Local folder containing manifest.json and the files referenced by its relative_path entries.

.PARAMETER Prune
    Delete files already in the library whose relative path is not present in the new manifest.
    Empty folders left behind after pruning are also removed.

.EXAMPLE
    .\scripts\Publish-SiteCorpusToSharePoint.ps1 `
        -SiteGraphPath "caldova37587778.sharepoint.com:/sites/hrknowledgehub" `
        -LibraryName 'Trusted Knowledge' `
        -CorpusPath '.state\site-corpora\hr' `
        -Prune
#>
[CmdletBinding()]
param(
    [string]$TenantId = (Get-Content -Raw (Join-Path $PSScriptRoot 'governance-targets.json') | ConvertFrom-Json).tenantId,
    [Parameter(Mandatory)][string]$SiteGraphPath,
    [Parameter(Mandatory)][string]$LibraryName,
    [Parameter(Mandatory)][string]$CorpusPath,
    [switch]$Prune
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
        [ValidateSet('GET', 'POST', 'PUT', 'DELETE')][string]$Method = 'GET',
        [Parameter(Mandatory)][string]$Uri,
        $Body = $null,
        [string]$InFile,
        [switch]$AllowNotFound
    )
    $requestUri = if ($Uri.StartsWith('https://')) { $Uri } else { "https://graph.microsoft.com/v1.0$Uri" }
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            $parameters = @{ Method = $Method; Uri = $requestUri; Headers = @{ Authorization = "Bearer $script:GraphToken" } }
            if ($InFile) {
                $parameters.InFile = $InFile
                $parameters.ContentType = 'application/octet-stream'
            }
            elseif ($null -ne $Body) {
                $parameters.Body = ConvertTo-Json -InputObject $Body -Depth 10 -Compress
                $parameters.ContentType = 'application/json'
            }
            $response = Invoke-WebRequest @parameters -ErrorAction Stop
            if ([string]::IsNullOrWhiteSpace($response.Content)) { return $null }
            return ($response.Content | ConvertFrom-Json)
        }
        catch {
            $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
            if ($AllowNotFound -and $status -eq 404) { return $null }
            if (($status -eq 429 -or $status -ge 500) -and $attempt -lt 6) {
                Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
                continue
            }
            $detail = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
            throw "Graph $Method $requestUri failed (HTTP $status): $detail"
        }
    }
}

function Get-GraphPages {
    param([Parameter(Mandatory)][string]$Uri)
    $next = $Uri
    while ($next) {
        $page = Invoke-Graph -Uri $next
        if ($null -eq $page) { break }
        foreach ($row in @($page.value)) { $row }
        $next = Get-Prop $page '@odata.nextLink'
    }
}

function ConvertTo-DrivePath {
    param([Parameter(Mandatory)][string]$RelativePath)
    return (($RelativePath -split '/') | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/'
}

function Ensure-DriveFolderPath {
    param([Parameter(Mandatory)][string]$DriveId, [Parameter(Mandatory)][string]$RelativeFolderPath)
    $segments = @(($RelativeFolderPath -replace '\\', '/').Split('/') | Where-Object { $_ })
    $currentPath = ''
    foreach ($segment in $segments) {
        $currentPath = if ($currentPath) { "$currentPath/$segment" } else { $segment }
        $encodedPath = ConvertTo-DrivePath -RelativePath $currentPath
        $existing = Invoke-Graph -Method GET -Uri "/drives/$DriveId/root:/$encodedPath" -AllowNotFound
        if (-not $existing) {
            $parentPath = Split-Path -Path $currentPath -Parent
            $parentUri = if ($parentPath -and $parentPath -ne '.') {
                "/drives/$DriveId/root:/$(ConvertTo-DrivePath -RelativePath $parentPath):/children"
            } else {
                "/drives/$DriveId/root/children"
            }
            Invoke-Graph -Method POST -Uri $parentUri -Body @{
                name = $segment; folder = @{}; '@microsoft.graph.conflictBehavior' = 'fail'
            } | Out-Null
        }
    }
}

function Get-DriveFilesRecursively {
    param([Parameter(Mandatory)][string]$DriveId)
    $results = @{}
    $pending = [System.Collections.Generic.Queue[string]]::new()
    $pending.Enqueue('')
    while ($pending.Count -gt 0) {
        $currentFolder = $pending.Dequeue()
        $uri = if ($currentFolder) {
            "/drives/$DriveId/root:/$(ConvertTo-DrivePath -RelativePath $currentFolder):/children?`$select=id,name,file,folder"
        } else {
            "/drives/$DriveId/root/children?`$select=id,name,file,folder"
        }
        foreach ($child in Get-GraphPages -Uri $uri) {
            $childPath = if ($currentFolder) { "$currentFolder/$($child.name)" } else { $child.name }
            if ($null -ne (Get-Prop $child 'file')) {
                $results[$childPath] = $child
            }
            elseif ($null -ne (Get-Prop $child 'folder')) {
                $pending.Enqueue($childPath)
            }
        }
    }
    return $results
}

Write-Host "Resolving site '$SiteGraphPath' and library '$LibraryName'..."
$site = Invoke-Graph -Uri "/sites/$SiteGraphPath"
$lists = @(Get-GraphPages -Uri "/sites/$($site.id)/lists?`$select=id,displayName,list")
$library = @($lists | Where-Object { $_.displayName -eq $LibraryName -and (Get-Prop $_.list 'template') -eq 'documentLibrary' }) | Select-Object -First 1
if (-not $library) { throw "Document library '$LibraryName' not found on site $SiteGraphPath." }
$drive = Invoke-Graph -Uri "/sites/$($site.id)/lists/$($library.id)/drive?`$select=id"
$driveId = $drive.id

$manifestPath = Join-Path $CorpusPath 'manifest.json'
if (-not (Test-Path $manifestPath)) { throw "Manifest not found: $manifestPath" }
$manifest = @(Get-Content -Raw -Path $manifestPath | ConvertFrom-Json)
Write-Host "Uploading $($manifest.Count) files from $CorpusPath ..."

$uploaded = 0
$desiredPaths = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($entry in $manifest) {
    $relativePath = ($entry.relative_path -replace '\\', '/')
    [void]$desiredPaths.Add($relativePath)
    $localPath = Join-Path $CorpusPath ($relativePath -replace '/', [IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path $localPath -PathType Leaf)) { throw "Missing local file for manifest entry: $localPath" }
    $folder = Split-Path -Path $relativePath -Parent
    if ($folder) { Ensure-DriveFolderPath -DriveId $driveId -RelativeFolderPath $folder }
    $encodedPath = ConvertTo-DrivePath -RelativePath $relativePath
    Invoke-Graph -Method PUT -Uri "/drives/$driveId/root:/$encodedPath`:/content" -InFile (Resolve-Path $localPath).Path | Out-Null
    $uploaded++
    if ($uploaded % 20 -eq 0) { Write-Host "  uploaded $uploaded / $($manifest.Count)" }
}
Write-Host "Uploaded $uploaded files."

if ($Prune) {
    Write-Host 'Checking for obsolete files to remove...'
    $existing = Get-DriveFilesRecursively -DriveId $driveId
    $removed = 0
    foreach ($path in $existing.Keys) {
        if ($path -eq 'manifest.json') { continue }
        if (-not $desiredPaths.Contains($path)) {
            Invoke-Graph -Method DELETE -Uri "/drives/$driveId/items/$($existing[$path].id)" -AllowNotFound | Out-Null
            $removed++
        }
    }
    Write-Host "Removed $removed obsolete file(s)."

    Write-Host 'Removing folders left empty after pruning...'
    $remainingFolders = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($path in $desiredPaths) {
        $parent = Split-Path -Path $path -Parent
        if ($parent) { [void]$remainingFolders.Add($parent) }
    }
    $topLevel = Invoke-Graph -Uri "/drives/$driveId/root/children?`$select=id,name,folder"
    foreach ($child in @($topLevel.value)) {
        if ((Get-Prop $child 'folder') -and -not $remainingFolders.Contains($child.name)) {
            $hasRemainingChild = @($remainingFolders) | Where-Object { $_ -eq $child.name -or $_.StartsWith("$($child.name)/") }
            if (-not $hasRemainingChild) {
                Invoke-Graph -Method DELETE -Uri "/drives/$driveId/items/$($child.id)" -AllowNotFound | Out-Null
                Write-Host "  removed empty folder: $($child.name)"
            }
        }
    }
}

Write-Host 'Done.'
