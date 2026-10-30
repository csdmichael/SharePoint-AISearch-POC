<#
.SYNOPSIS
    Adds exact and near-duplicate copies of source documents to a document library.

.DESCRIPTION
    Generalizes the earlier script that uploaded fixed Semiconductor pairs from local paths. For the library given by
    -SiteUrl and -LibraryName it takes .docx source files in name order:
      - exact copies: the same document text, saved as "<name> (copy).docx" in the same folder;
      - near copies:  the same document with a few words edited, saved as "<name> (edited copy).docx". Numbers are not
                      changed, so the numeric fingerprint matches and the text stays similar to the source.

    A .docx carries its Document Information Panel values in a customXml part (the one holding documentManagement).
    SharePoint copies those values into the list columns on upload, so a copy would take its source's unique ArtifactId
    and be rejected. Such a copy gets a unique placeholder first, and its final value ART-<SITE>-<listItemId> is written
    through the list item once the upload exists. The SITE tag comes from governance-targets.json (or -SiteTag).

    Only the placeholder text and the wording of w:t text nodes change. Every other package part stays byte-identical.

    Source bytes are read through Microsoft Graph with a read-only app identity created for the run. SharePoint rejects
    the delegated Azure CLI token on the content redirect, so the app is required for reads. Uploads and metadata writes
    use the Azure CLI user token. The app is deleted in a finally block, even when the run fails.

    Verification before each upload: an exact copy must match its source in every package part except the ArtifactId
    placeholder. A near copy must keep the same numbers in document order and must contain at least -MinimumNearEdits
    word replacements. Existing copies are kept, so re-running is safe.

.PARAMETER SiteUrl
    Site URL, for example https://caldova37587778.sharepoint.com/sites/hrknowledgehub

.PARAMETER LibraryName
    Display name of the document library, for example "Documents".

.PARAMETER ExactCopies
    Number of source files to copy with identical text.

.PARAMETER NearCopies
    Number of further source files to copy with edited wording.

.PARAMETER MinimumNearEdits
    Fewest word replacements a near copy must contain. A source with fewer is skipped.

.PARAMETER SiteTag
    Site tag for ArtifactId values. Defaults to the siteId of the matching site in governance-targets.json.

.EXAMPLE
    .\scripts\Upload-DuplicatePairs.ps1 -SiteUrl https://caldova37587778.sharepoint.com/sites/hrknowledgehub -LibraryName "Documents"
#>
[CmdletBinding()]
param(
    [string]$TenantId = '12a4b86b-e64c-43f9-af05-d9130a72dfd2',
    [Parameter(Mandatory)][string]$SiteUrl,
    [Parameter(Mandatory)][string]$LibraryName,
    [ValidateRange(0, 20)][int]$ExactCopies = 2,
    [ValidateRange(0, 20)][int]$NearCopies = 2,
    [ValidateRange(1, 100)][int]$MinimumNearEdits = 4,
    [string]$SiteTag
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$graphAppId = '00000003-0000-0000-c000-000000000000'
$readRoles = @('Sites.Read.All', 'Files.Read.All')
# Whole-word wording swaps for near copies. None of them touches a digit, so the numeric content is unchanged.
$wordSwaps = @(
    @('ensure', 'confirm'), @('Ensure', 'Confirm'),
    @('provide', 'supply'), @('Provide', 'Supply'),
    @('within', 'inside'), @('Within', 'Inside'),
    @('approximately', 'about'), @('Approximately', 'About'),
    @('typically', 'usually'), @('Typically', 'Usually'),
    @('identify', 'determine'), @('Identify', 'Determine'),
    @('important', 'critical'), @('Important', 'Critical'),
    @('several', 'multiple'), @('Several', 'Multiple'),
    @('maintain', 'keep'), @('Maintain', 'Keep')
)

$siteUri = [Uri]$SiteUrl
$graphSitePath = "$($siteUri.Host):$($siteUri.AbsolutePath.TrimEnd('/'))"
if ([string]::IsNullOrWhiteSpace($SiteTag)) {
    $targets = Get-Content -Raw -Path (Join-Path $PSScriptRoot 'governance-targets.json') | ConvertFrom-Json
    $matchingSites = @($targets.sites | Where-Object { $_.siteUrl -ieq $SiteUrl.TrimEnd('/') })
    if ($matchingSites.Count -ne 1) { throw "No site in governance-targets.json matches $SiteUrl. Pass -SiteTag." }
    $SiteTag = [string]$matchingSites[0].siteId
}
$artifactTag = $SiteTag.ToUpperInvariant()

$script:UserToken = (az account get-access-token --tenant $TenantId --resource https://graph.microsoft.com --query accessToken -o tsv)
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

function New-ReadOnlyGraphApp {
    param([string]$Stamp)
    $graphServicePrincipal = @((Invoke-Api -Uri "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '$graphAppId'&`$select=id,appId,appRoles").value)[0]
    $roleIds = @{}
    foreach ($role in $readRoles) {
        $match = @($graphServicePrincipal.appRoles | Where-Object { $_.value -eq $role -and $_.allowedMemberTypes -contains 'Application' })
        if ($match.Count -ne 1) { throw "Microsoft Graph application role $role was not found." }
        $roleIds[$role] = $match[0].id
    }
    $app = Invoke-Api -Method POST -Uri 'https://graph.microsoft.com/v1.0/applications' -Body @{
        displayName            = "Governance Duplicate Source Reader $Stamp"
        signInAudience         = 'AzureADMyOrg'
        requiredResourceAccess = @(@{
                resourceAppId  = $graphAppId
                resourceAccess = @($readRoles | ForEach-Object { @{ id = $roleIds[$_]; type = 'Role' } })
            })
    }
    $script:CreatedAppId = [string]$app.id
    $servicePrincipal = Invoke-Api -Method POST -Uri 'https://graph.microsoft.com/v1.0/servicePrincipals' -Body @{ appId = $app.appId }
    foreach ($role in $readRoles) {
        Invoke-Api -Method POST -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$($servicePrincipal.id)/appRoleAssignments" -Body @{
            principalId = $servicePrincipal.id
            resourceId  = $graphServicePrincipal.id
            appRoleId   = $roleIds[$role]
        } | Out-Null
    }
    $password = Invoke-Api -Method POST -Uri "https://graph.microsoft.com/v1.0/applications/$($app.id)/addPassword" -Body @{
        passwordCredential = @{ displayName = 'run'; endDateTime = (Get-Date).ToUniversalTime().AddHours(2).ToString('o') }
    }
    return [pscustomobject]@{ ClientId = $app.appId; Secret = $password.secretText }
}

function Get-ReadOnlyToken {
    param($App)
    $lastResult = 'no response'
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $response = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -Body @{
                client_id     = $App.ClientId
                client_secret = $App.Secret
                scope         = 'https://graph.microsoft.com/.default'
                grant_type    = 'client_credentials'
            }
            $roles = @((Get-JwtClaims -Token $response.access_token).roles)
            if (@($readRoles | Where-Object { $roles -notcontains $_ }).Count -eq 0) { return $response.access_token }
            $lastResult = "token roles were $($roles -join ', ')"
        }
        catch { $lastResult = $_.Exception.Message }
        Start-Sleep -Seconds 4
    }
    throw "The read-only app token did not receive its Graph roles in time. Last result: $lastResult"
}

function Get-DriveItemContent {
    param([Parameter(Mandatory)][string]$Url, [Parameter(Mandatory)][string]$Token)
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    try {
        $current = $Url
        for ($hop = 0; $hop -lt 5; $hop++) {
            $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $current)
            $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $Token)
            $response = $client.SendAsync($request).GetAwaiter().GetResult()
            try {
                $code = [int]$response.StatusCode
                if ($code -ge 300 -and $code -lt 400) {
                    $location = $response.Headers.Location
                    $current = if ($location.IsAbsoluteUri) { $location.AbsoluteUri } else { [Uri]::new([Uri]$current, $location).AbsoluteUri }
                    continue
                }
                if (-not $response.IsSuccessStatusCode) { throw "Content download failed with HTTP $code." }
                return $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
            }
            finally { $response.Dispose() }
        }
        throw 'Content download exceeded the redirect limit.'
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Read-ZipEntryBytes {
    param([Parameter(Mandatory)]$Entry)
    $buffer = [System.IO.MemoryStream]::new()
    $stream = $Entry.Open()
    try { $stream.CopyTo($buffer) } finally { $stream.Dispose() }
    return $buffer.ToArray()
}

function Get-ZipEntries {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    Add-Type -AssemblyName System.IO.Compression
    $stream = [System.IO.MemoryStream]::new($Bytes)
    $zip = [System.IO.Compression.ZipArchive]::new($stream, [System.IO.Compression.ZipArchiveMode]::Read)
    try {
        $entries = [ordered]@{}
        foreach ($entry in $zip.Entries) { $entries[$entry.FullName] = Read-ZipEntryBytes -Entry $entry }
        return $entries
    }
    finally {
        $zip.Dispose()
        $stream.Dispose()
    }
}

function Set-ArtifactIdText {
    param([Parameter(Mandatory)][string]$Xml, [Parameter(Mandatory)][AllowEmptyString()][string]$Value)
    $hits = @([regex]::Matches($Xml, '<ArtifactId\b([^>]*?)(/>|>[^<]*</ArtifactId>)'))
    if ($hits.Count -ne 1) { throw "Expected one ArtifactId element in the document properties; found $($hits.Count)." }
    $hit = $hits[0]
    $attributes = $hit.Groups[1].Value -replace '\s+xsi:nil="true"', ''
    return $Xml.Substring(0, $hit.Index) + "<ArtifactId$attributes>$Value</ArtifactId>" + $Xml.Substring($hit.Index + $hit.Length)
}

function Edit-WordingXml {
    param([Parameter(Mandatory)][string]$Xml)
    $state = [pscustomobject]@{ Edits = 0 }
    $evaluator = [System.Text.RegularExpressions.MatchEvaluator]{
        param($match)
        $text = $match.Groups[2].Value
        foreach ($swap in $wordSwaps) {
            $pattern = '\b' + [regex]::Escape($swap[0]) + '\b'
            $found = [regex]::Matches($text, $pattern).Count
            if ($found -gt 0) {
                $state.Edits += $found
                $text = [regex]::Replace($text, $pattern, $swap[1])
            }
        }
        return $match.Groups[1].Value + $text + $match.Groups[3].Value
    }
    $edited = [regex]::Replace($Xml, '(<w:t(?:\s[^>]*)?>)([^<]*)(</w:t>)', $evaluator)
    return [pscustomobject]@{ Xml = $edited; Edits = $state.Edits }
}

function New-DocxCopyBytes {
    param(
        [Parameter(Mandatory)][byte[]]$SourceBytes,
        [Parameter(Mandatory)][string]$ArtifactPlaceholder,
        [switch]$EditWording
    )
    Add-Type -AssemblyName System.IO.Compression
    $utf8 = [Text.UTF8Encoding]::new($false)
    $sourceStream = [System.IO.MemoryStream]::new($SourceBytes)
    $outputStream = [System.IO.MemoryStream]::new()
    $edits = 0
    $propertiesParts = 0
    $sourceZip = [System.IO.Compression.ZipArchive]::new($sourceStream, [System.IO.Compression.ZipArchiveMode]::Read)
    $outputZip = [System.IO.Compression.ZipArchive]::new($outputStream, [System.IO.Compression.ZipArchiveMode]::Create, $true)
    try {
        foreach ($entry in $sourceZip.Entries) {
            $bytes = Read-ZipEntryBytes -Entry $entry
            if ($EditWording -and $entry.FullName -eq 'word/document.xml') {
                $edited = Edit-WordingXml -Xml $utf8.GetString($bytes)
                $edits = $edited.Edits
                $bytes = $utf8.GetBytes($edited.Xml)
            }
            elseif ($entry.FullName -like 'customXml/*.xml' -and $utf8.GetString($bytes).Contains('<documentManagement')) {
                $bytes = $utf8.GetBytes((Set-ArtifactIdText -Xml $utf8.GetString($bytes) -Value $ArtifactPlaceholder))
                $propertiesParts++
            }
            $newEntry = $outputZip.CreateEntry($entry.FullName, [System.IO.Compression.CompressionLevel]::Optimal)
            $newStream = $newEntry.Open()
            try { $newStream.Write($bytes, 0, $bytes.Length) } finally { $newStream.Dispose() }
        }
    }
    finally {
        $outputZip.Dispose()
        $sourceZip.Dispose()
    }
    return [pscustomobject]@{ Bytes = $outputStream.ToArray(); Edits = $edits; PropertiesParts = $propertiesParts }
}

function Test-SameBytes {
    param([byte[]]$Left, [byte[]]$Right)
    $leftHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Left))
    $rightHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Right))
    return $leftHash -ceq $rightHash
}

function Assert-ExactCopy {
    param([byte[]]$SourceBytes, [byte[]]$CopyBytes)
    $source = Get-ZipEntries -Bytes $SourceBytes
    $copy = Get-ZipEntries -Bytes $CopyBytes
    $sourceParts = (@($source.Keys) -join '|')
    $copyParts = (@($copy.Keys) -join '|')
    if ($sourceParts -cne $copyParts) { throw 'The copy has different package parts from its source.' }
    foreach ($part in $source.Keys) {
        $sourceText = if ($part -like 'customXml/*.xml') { [Text.Encoding]::UTF8.GetString($source[$part]) } else { '' }
        if ($sourceText.Contains('<documentManagement')) {
            $sourceProperties = Set-ArtifactIdText -Xml $sourceText -Value ''
            $copyProperties = Set-ArtifactIdText -Xml ([Text.Encoding]::UTF8.GetString($copy[$part])) -Value ''
            if ($sourceProperties -cne $copyProperties) { throw 'The copy differs from its source in document properties beyond ArtifactId.' }
        }
        elseif (-not (Test-SameBytes -Left $source[$part] -Right $copy[$part])) {
            throw "The copy differs from its source in $part."
        }
    }
}

function Assert-NearCopy {
    param([byte[]]$SourceBytes, [byte[]]$CopyBytes, [int]$MinimumEdits, [int]$Edits)
    $sourceText = [Text.Encoding]::UTF8.GetString((Get-ZipEntries -Bytes $SourceBytes)['word/document.xml'])
    $copyText = [Text.Encoding]::UTF8.GetString((Get-ZipEntries -Bytes $CopyBytes)['word/document.xml'])
    $sourceNumbers = @([regex]::Matches($sourceText, '\d+') | ForEach-Object { $_.Value })
    $copyNumbers = @([regex]::Matches($copyText, '\d+') | ForEach-Object { $_.Value })
    if ((@($sourceNumbers) -join ' ') -cne (@($copyNumbers) -join ' ')) {
        throw 'The edited copy changed a number, so it would not be a near duplicate.'
    }
    if ($sourceText -ceq $copyText) { throw 'The edited copy has the same wording as its source.' }
    if ($Edits -lt $MinimumEdits) { throw "The edited copy has $Edits word edits; $MinimumEdits are required." }
}

function Send-NewDriveItem {
    param([string]$DriveId, [string]$ParentItemId, [string]$FileName, [byte[]]$Bytes)
    $escapedName = [Uri]::EscapeDataString($FileName)
    $uri = "https://graph.microsoft.com/v1.0/drives/$DriveId/items/$ParentItemId`:/$escapedName`:/content?@microsoft.graph.conflictBehavior=fail"
    $response = Invoke-WebRequest -Method PUT -Uri $uri -Headers @{ Authorization = "Bearer $script:UserToken" } `
        -Body $Bytes -ContentType 'application/octet-stream' -ErrorAction Stop
    return ($response.Content | ConvertFrom-Json -DateKind String)
}

$stamp = Get-Date -Format 'yyyyMMddHHmmss'
try {
    $app = New-ReadOnlyGraphApp -Stamp $stamp
    $readToken = Get-ReadOnlyToken -App $app

    $siteId = [string](Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$graphSitePath").id
    $lists = @((Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/lists?`$select=id,displayName,name,list&`$top=200").value)
    $library = @($lists | Where-Object { $_.displayName -eq $LibraryName -and (Get-Prop $_.list 'template') -eq 'documentLibrary' })
    if ($library.Count -ne 1) { throw "Expected exactly one document library named '$LibraryName' at $SiteUrl; found $($library.Count)." }
    $listId = [string]$library[0].id
    $driveId = [string](Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/lists/$listId/drive").id

    $items = [System.Collections.Generic.List[object]]::new()
    $next = "https://graph.microsoft.com/v1.0/sites/$siteId/lists/$listId/items?`$expand=fields&`$top=999"
    while ($next) {
        $page = Invoke-Api -Uri $next
        foreach ($row in @($page.value)) { $items.Add($row) }
        $next = Get-Prop $page '@odata.nextLink'
    }
    $files = @($items | Where-Object { (Get-Prop $_.fields 'ContentType') -ne 'Folder' })
    $existingNames = @($files | ForEach-Object { [string](Get-Prop $_.fields 'FileLeafRef') })

    $copyPattern = '\s\((edited\s)?copy\)\.docx$'
    $sources = @($files |
            Where-Object { ([string](Get-Prop $_.fields 'FileLeafRef')) -like '*.docx' -and ([string](Get-Prop $_.fields 'FileLeafRef')) -notmatch $copyPattern } |
            Sort-Object { ([string](Get-Prop $_.fields 'FileLeafRef')).ToLowerInvariant() })
    if ($sources.Count -lt ($ExactCopies + $NearCopies)) {
        throw "Only $($sources.Count) source .docx files are available; $($ExactCopies + $NearCopies) are required."
    }
    Write-Host "Library '$LibraryName' at $SiteUrl : $($files.Count) files, $($sources.Count) .docx sources, ArtifactId tag $artifactTag." -ForegroundColor Cyan

    $created = 0
    $existing = 0

    function Add-Copy {
        param($Source, [string]$CopyName, [switch]$EditWording, [int]$MinimumEdits)
        $sourceName = [string](Get-Prop $Source.fields 'FileLeafRef')
        $sourceItem = Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/lists/$listId/items/$($Source.id)/driveItem"
        $sourceBytes = Get-DriveItemContent -Url "https://graph.microsoft.com/v1.0/drives/$driveId/items/$($sourceItem.id)/content" -Token $readToken
        if ($sourceBytes.Length -ne [int64]$sourceItem.size) {
            throw "${sourceName}: downloaded $($sourceBytes.Length) bytes, expected $($sourceItem.size)."
        }
        $placeholder = 'ART-PENDING-' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
        $package = New-DocxCopyBytes -SourceBytes $sourceBytes -ArtifactPlaceholder $placeholder -EditWording:$EditWording
        if ($EditWording) {
            if ($package.Edits -lt $MinimumEdits) {
                Write-Host "  skipped ${sourceName}: $($package.Edits) word edits, $MinimumEdits required." -ForegroundColor Yellow
                return $false
            }
            Assert-NearCopy -SourceBytes $sourceBytes -CopyBytes $package.Bytes -MinimumEdits $MinimumEdits -Edits $package.Edits
        }
        else {
            Assert-ExactCopy -SourceBytes $sourceBytes -CopyBytes $package.Bytes
        }
        $uploaded = Send-NewDriveItem -DriveId $driveId -ParentItemId ([string]$sourceItem.parentReference.id) -FileName $CopyName -Bytes $package.Bytes
        if ([int64]$uploaded.size -ne $package.Bytes.Length) {
            throw "$CopyName was stored with $($uploaded.size) bytes; $($package.Bytes.Length) were sent."
        }
        $listItem = Invoke-Api -Uri "https://graph.microsoft.com/v1.0/drives/$driveId/items/$($uploaded.id)/listItem"
        $listItemId = [string]$listItem.id
        $current = Invoke-Api -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/lists/$listId/items/$listItemId`?`$expand=fields"
        $currentArtifact = [string](Get-Prop $current.fields 'ArtifactId')
        $expectedBefore = if ($package.PropertiesParts -gt 0) { $placeholder } else { '' }
        if ($currentArtifact -cne $expectedBefore) {
            throw "New item $listItemId has ArtifactId '$currentArtifact'; expected '$expectedBefore' before the final value is written."
        }
        $artifactId = "ART-$artifactTag-$listItemId"
        Invoke-Api -Method PATCH -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/lists/$listId/items/$listItemId/fields" -Body @{ ArtifactId = $artifactId } | Out-Null
        $kind = if ($EditWording) { "near copy ($($package.Edits) word edits)" } else { 'exact copy' }
        Write-Host "  $kind created: $CopyName from $sourceName, ArtifactId $artifactId" -ForegroundColor Green
        return $true
    }

    for ($index = 0; $index -lt $ExactCopies; $index++) {
        $source = $sources[$index]
        $sourceName = [string](Get-Prop $source.fields 'FileLeafRef')
        $copyName = [IO.Path]::GetFileNameWithoutExtension($sourceName) + ' (copy)' + [IO.Path]::GetExtension($sourceName)
        if ($existingNames -contains $copyName) { $existing++; Write-Host "  exact copy exists: $copyName"; continue }
        if (Add-Copy -Source $source -CopyName $copyName) { $created++ }
    }

    $nearCreated = 0
    for ($index = $ExactCopies; $index -lt $sources.Count -and $nearCreated -lt $NearCopies; $index++) {
        $source = $sources[$index]
        $sourceName = [string](Get-Prop $source.fields 'FileLeafRef')
        $copyName = [IO.Path]::GetFileNameWithoutExtension($sourceName) + ' (edited copy)' + [IO.Path]::GetExtension($sourceName)
        if ($existingNames -contains $copyName) { $existing++; $nearCreated++; Write-Host "  near copy exists: $copyName"; continue }
        if (Add-Copy -Source $source -CopyName $copyName -EditWording -MinimumEdits $MinimumNearEdits) {
            $created++
            $nearCreated++
        }
    }
    if ($nearCreated -lt $NearCopies) {
        throw "Only $nearCreated of $NearCopies near copies were produced. Lower -MinimumNearEdits or check the sources."
    }
    Write-Host "Done. Created $created copies; $existing already existed." -ForegroundColor Green
}
finally {
    if ($script:CreatedAppId) {
        try {
            Invoke-Api -Method DELETE -Uri "https://graph.microsoft.com/v1.0/applications/$($script:CreatedAppId)" | Out-Null
            Write-Host 'Deleted the temporary read-only app.'
        }
        catch {
            Write-Warning "Could not delete temporary app $($script:CreatedAppId): $($_.Exception.Message)"
        }
    }
}
