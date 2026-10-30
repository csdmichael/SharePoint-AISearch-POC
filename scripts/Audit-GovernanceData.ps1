<#
.SYNOPSIS
    Read-only audit of the governance data in the target document libraries.

.DESCRIPTION
    Reads every file in the libraries listed in governance-targets.json and reports, per library:
      - item count and DocumentIteration / LifecycleStatus distribution;
      - Authoritative, ReviewDate and ExpirationDate past-date counts;
      - owner coverage (OwnerDisplayName and the KnowledgeOwner person field);
      - missing values for the columns that every file must carry;
      - exact and near duplicate candidates (shared ContentHash, DuplicateOf with a different hash);
      - governance-computed distribution (DataQualityStatus, ConflictStatus, AIReady, TrustScore);
      - checks: ArtifactId unique and set, iteration spread, lifecycle-date rules, no checkouts left behind.
    It writes nothing. It exits with code 1 when any check fails.

.PARAMETER TargetsPath
    Library list. Defaults to governance-targets.json beside this script.

.PARAMETER SiteId
    Optional siteId from the targets file to audit one site.
#>
[CmdletBinding()]
param(
    [string]$TargetsPath = (Join-Path $PSScriptRoot 'governance-targets.json'),
    [string]$SiteId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$targets = Get-Content -Raw -Path $TargetsPath | ConvertFrom-Json -DateKind String
$script:GraphToken = (az account get-access-token --tenant $targets.tenantId --resource https://graph.microsoft.com --query accessToken -o tsv)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($script:GraphToken)) {
    throw 'Could not get a Microsoft Graph token from Azure CLI. Run az login for the tenant and retry.'
}
$script:GraphToken = $script:GraphToken.Trim()
$today = [DateTime]::UtcNow.Date.ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
$iterationValues = @('Draft', 'Ready', 'In Review', 'Approved', 'Archived')
$lifecycleValues = @('Draft', 'Published', 'Superseded', 'Archived')
$setColumns = @('DocumentIteration', 'LifecycleStatus', 'Sensitivity', 'DocumentType', 'ProcessArea',
    'KnowledgeCategory', 'ProductFamily', 'BusinessUnit', 'SourceSystem', 'ArtifactId')
$computedColumns = @('DataQualityStatus', 'ConflictStatus', 'TrustScore', 'AIReady', 'LastValidatedDate')
$script:checkFailures = [System.Collections.Generic.List[string]]::new()

function Get-Prop {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Invoke-Graph {
    param([Parameter(Mandatory)][string]$Uri)
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -Headers @{ Authorization = "Bearer $script:GraphToken" } -ErrorAction Stop
            return ($response.Content | ConvertFrom-Json -DateKind String)
        }
        catch {
            $statusCode = 0
            if ($_.Exception.Response) { $statusCode = [int]$_.Exception.Response.StatusCode }
            if (($statusCode -in 429, 500, 502, 503, 504) -and $attempt -lt 6) {
                Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
                continue
            }
            throw "GET $Uri failed (HTTP $statusCode): $($_.Exception.Message)"
        }
    }
}

function Get-LibraryFiles {
    param([string]$SiteGraphId, [string]$ListId)
    $rows = [System.Collections.Generic.List[object]]::new()
    $next = "https://graph.microsoft.com/v1.0/sites/$SiteGraphId/lists/$ListId/items?`$expand=fields&`$top=999"
    while ($next) {
        $page = Invoke-Graph -Uri $next
        foreach ($row in @($page.value)) { $rows.Add($row) }
        $next = Get-Prop $page '@odata.nextLink'
    }
    return @($rows | Where-Object { (Get-Prop $_.fields 'ContentType') -ne 'Folder' })
}

function Add-Check {
    param([string]$Label, [bool]$Passed, [string]$Detail)
    $mark = if ($Passed) { 'PASS' } else { 'FAIL' }
    $color = if ($Passed) { 'Green' } else { 'Red' }
    Write-Host ("  [{0}] {1}: {2}" -f $mark, $Label, $Detail) -ForegroundColor $color
    if (-not $Passed) { $script:checkFailures.Add("$Label ($Detail)") }
}

function Get-Date10 {
    param($Value)
    $text = [string]$Value
    if ([string]::IsNullOrEmpty($text)) { return $null }
    return $text.Substring(0, 10)
}

$selectedSites = @($targets.sites | Where-Object { -not $SiteId -or $_.siteId -eq $SiteId })
$totalFiles = 0
$libraryTotal = 0
foreach ($site in $selectedSites) {
    $siteGraphId = [string](Invoke-Graph -Uri "https://graph.microsoft.com/v1.0/sites/$($site.graphPath)").id
    foreach ($libraryName in @($site.libraries)) {
        $libraryTotal++
        $failuresBefore = $script:checkFailures.Count
        $lists = @((Invoke-Graph -Uri "https://graph.microsoft.com/v1.0/sites/$siteGraphId/lists?`$select=id,displayName,name,list&`$top=200").value)
        $library = @($lists | Where-Object { $_.displayName -eq $libraryName -and (Get-Prop $_.list 'template') -eq 'documentLibrary' })
        if ($library.Count -ne 1) { throw "Expected exactly one document library named '$libraryName' in $($site.siteId)." }
        $files = @(Get-LibraryFiles -SiteGraphId $siteGraphId -ListId ([string]$library[0].id))
        $totalFiles += $files.Count
        Write-Host "`n== $($site.siteId) / $libraryName : $($files.Count) files" -ForegroundColor Cyan
        if ($files.Count -eq 0) { Write-Host '  no files'; continue }

        $iterations = @{}; foreach ($v in $iterationValues) { $iterations[$v] = 0 }
        $lifecycles = @{}; foreach ($v in $lifecycleValues) { $lifecycles[$v] = 0 }
        $missing = @{}; foreach ($c in $setColumns) { $missing[$c] = 0 }
        $computedMissing = @{}; foreach ($c in $computedColumns) { $computedMissing[$c] = 0 }
        $quality = @{}; $conflicts = @{}
        $authoritative = 0; $aiReady = 0; $scores = [System.Collections.Generic.List[double]]::new()
        $reviewSet = 0; $reviewPast = 0; $expirySet = 0; $expiryPast = 0
        $effectiveMissing = 0; $reviewMissingPublished = 0
        $ownerNameEmpty = 0; $personEmpty = 0; $noOwner = 0; $checkedOut = 0
        $artifactIds = @{}; $names = @{}; $hashes = @{}; $duplicateOf = [System.Collections.Generic.List[object]]::new()
        $copyNames = 0; $editedCopyNames = 0

        foreach ($file in $files) {
            $fields = $file.fields
            $name = [string](Get-Prop $fields 'FileLeafRef')
            $names[$name] = $true
            if ($name -like '* (copy).*') { $copyNames++ }
            if ($name -like '* (edited copy).*') { $editedCopyNames++ }
            $iteration = [string](Get-Prop $fields 'DocumentIteration')
            if ($iterations.ContainsKey($iteration)) { $iterations[$iteration]++ }
            $lifecycle = [string](Get-Prop $fields 'LifecycleStatus')
            if ($lifecycles.ContainsKey($lifecycle)) { $lifecycles[$lifecycle]++ }
            if ($null -ne (Get-Prop $fields 'Authoritative') -and [bool](Get-Prop $fields 'Authoritative')) { $authoritative++ }
            foreach ($c in $setColumns) {
                if ([string]::IsNullOrEmpty([string](Get-Prop $fields $c))) { $missing[$c]++ }
            }
            if ($lifecycle -in 'Published', 'Superseded', 'Archived' -and [string]::IsNullOrEmpty([string](Get-Prop $fields 'EffectiveDate'))) { $effectiveMissing++ }
            if ($lifecycle -eq 'Published' -and [string]::IsNullOrEmpty([string](Get-Prop $fields 'ReviewDate'))) { $reviewMissingPublished++ }
            $review = Get-Date10 (Get-Prop $fields 'ReviewDate')
            if ($review) { $reviewSet++; if ($review -lt $today) { $reviewPast++ } }
            $expiry = Get-Date10 (Get-Prop $fields 'ExpirationDate')
            if ($expiry) { $expirySet++; if ($expiry -lt $today) { $expiryPast++ } }
            $ownerName = [string](Get-Prop $fields 'OwnerDisplayName')
            $lookup = [string](Get-Prop $fields 'KnowledgeOwnerLookupId')
            if ([string]::IsNullOrEmpty($ownerName)) { $ownerNameEmpty++ }
            if ([string]::IsNullOrEmpty($lookup)) { $personEmpty++ }
            if ([string]::IsNullOrEmpty($ownerName) -and [string]::IsNullOrEmpty($lookup)) { $noOwner++ }
            if ([string]::IsNullOrEmpty([string](Get-Prop $fields 'CheckoutUserLookupId')) -eq $false) { $checkedOut++ }
            $artifact = [string](Get-Prop $fields 'ArtifactId')
            if ($artifact) { $artifactIds[$artifact] = 1 + [int]$artifactIds[$artifact] }
            foreach ($c in $computedColumns) {
                if ([string]::IsNullOrEmpty([string](Get-Prop $fields $c))) { $computedMissing[$c]++ }
            }
            $quality[[string](Get-Prop $fields 'DataQualityStatus')] = 1 + [int]$quality[[string](Get-Prop $fields 'DataQualityStatus')]
            $conflicts[[string](Get-Prop $fields 'ConflictStatus')] = 1 + [int]$conflicts[[string](Get-Prop $fields 'ConflictStatus')]
            if ($null -ne (Get-Prop $fields 'AIReady') -and [bool](Get-Prop $fields 'AIReady')) { $aiReady++ }
            $score = Get-Prop $fields 'TrustScore'
            if ($null -ne $score -and [string]$score -ne '') { $scores.Add([double]$score) }
            $hash = [string](Get-Prop $fields 'ContentHash')
            if ($hash) { $hashes[$name] = $hash }
            $dupOf = [string](Get-Prop $fields 'DuplicateOf')
            if ($dupOf) { $duplicateOf.Add([pscustomobject]@{ Name = $name; Canonical = $dupOf; Hash = $hash }) }
        }

        Write-Host ("  iterations: " + (($iterationValues | ForEach-Object { "$_=$($iterations[$_])" }) -join ', '))
        Write-Host ("  lifecycle:  " + (($lifecycleValues | ForEach-Object { "$_=$($lifecycles[$_])" }) -join ', '))
        Write-Host "  authoritative=$authoritative; ReviewDate set=$reviewSet (past $reviewPast); ExpirationDate set=$expirySet (past $expiryPast)"
        Write-Host "  owners: OwnerDisplayName empty=$ownerNameEmpty; person field empty=$personEmpty; no owner at all=$noOwner"
        $exactGroups = @($hashes.GetEnumerator() | Group-Object { $_.Value } | Where-Object Count -gt 1)
        $exactItems = if ($exactGroups.Count) { ($exactGroups | Measure-Object -Property Count -Sum).Sum } else { 0 }
        $exactPairs = if ($exactGroups.Count) { ($exactGroups | ForEach-Object { $_.Count * ($_.Count - 1) / 2 } | Measure-Object -Sum).Sum } else { 0 }
        $nearMembers = @($duplicateOf | Where-Object { -not $_.Hash -or -not $hashes.ContainsKey($_.Canonical) -or $hashes[$_.Canonical] -ne $_.Hash })
        Write-Host "  duplicates: items sharing a ContentHash=$([int]$exactItems) in $($exactGroups.Count) group(s) ($([int]$exactPairs) exact pairs); DuplicateOf set=$($duplicateOf.Count); near members (hash differs from canonical)=$($nearMembers.Count); copies named '(copy)'=$copyNames, '(edited copy)'=$editedCopyNames"
        Write-Host ("  DataQualityStatus: " + (($quality.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ', '))
        Write-Host ("  ConflictStatus:    " + (($conflicts.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ', '))
        $scoreText = if ($scores.Count) { "min $([Math]::Round(($scores | Measure-Object -Minimum).Minimum)), avg $([Math]::Round(($scores | Measure-Object -Average).Average, 1)), max $([Math]::Round(($scores | Measure-Object -Maximum).Maximum))" } else { 'none' }
        Write-Host "  AIReady=$aiReady; TrustScore $scoreText"

        $iterationMinimum = if ($files.Count -ge 5) { ($iterationValues | ForEach-Object { $iterations[$_] } | Measure-Object -Minimum).Minimum } else { $null }
        $iterationDetail = ($iterationValues | ForEach-Object { "$_=$($iterations[$_])" }) -join ', '
        if ($files.Count -ge 5) {
            # Most documents are approved; every other state must still be represented so the cleanup demo has examples.
            $approvedShare = $iterations['Approved'] / $files.Count
            $others = @($iterationValues | Where-Object { $_ -ne 'Approved' } | ForEach-Object { $iterations[$_] })
            Add-Check -Label 'iteration spread (approved majority, every other state present)' -Passed (($approvedShare -ge 0.5) -and (($others | Measure-Object -Minimum).Minimum -ge 1)) -Detail $iterationDetail
        }
        $missingDetail = ($setColumns | Where-Object { $missing[$_] -gt 0 } | ForEach-Object { "$_=$($missing[$_])" }) -join ', '
        Add-Check -Label 'governance columns set on every file' -Passed ($missingDetail -eq '') -Detail $(if ($missingDetail) { "missing $missingDetail" } else { 'none missing' })
        Add-Check -Label 'Published items have EffectiveDate and ReviewDate' -Passed (($effectiveMissing + $reviewMissingPublished) -eq 0) -Detail "EffectiveDate missing $effectiveMissing, ReviewDate missing $reviewMissingPublished"
        Add-Check -Label 'ArtifactId unique' -Passed (@($artifactIds.Values | Where-Object { $_ -gt 1 }).Count -eq 0) -Detail "$($artifactIds.Count) distinct values"
        $computedDetail = ($computedColumns | Where-Object { $computedMissing[$_] -gt 0 } | ForEach-Object { "$_=$($computedMissing[$_])" }) -join ', '
        Add-Check -Label 'governance-computed columns present' -Passed ($computedDetail -eq '') -Detail $(if ($computedDetail) { "missing $computedDetail" } else { 'present on every file' })
        Add-Check -Label 'no checkouts left' -Passed ($checkedOut -eq 0) -Detail "$checkedOut checked out"
        if ($site.siteId -ne 'semiconductor' -and $libraryName -eq 'Documents') {
            Add-Check -Label 'duplicate copies added' -Passed ($copyNames -ge 2 -and $editedCopyNames -ge 2) -Detail "exact copies $copyNames, edited copies $editedCopyNames"
        }
        if ($script:checkFailures.Count -eq $failuresBefore) { Write-Host '  all checks passed for this library' -ForegroundColor Green }
    }
}

Write-Host "`nAudited $totalFiles files across $libraryTotal libraries."
if ($script:checkFailures.Count -gt 0) {
    Write-Host "$($script:checkFailures.Count) check(s) failed:" -ForegroundColor Red
    foreach ($failure in $script:checkFailures) { Write-Host "  - $failure" -ForegroundColor Red }
    exit 1
}
Write-Host 'All audit checks passed.' -ForegroundColor Green
