<#
.SYNOPSIS
    Seeds declared governance metadata into the knowledge document libraries (Documents, meeting libraries and the semiconductor library).

.DESCRIPTION
    Replaces the earlier seeding script, which swallowed every error with an empty catch and reported success
    without checking. This version:
      - authenticates with the Azure CLI user token (no ephemeral app);
      - derives every value from the file's position in its library (files sorted by name), its name and its site,
        so a re-run computes the same values and writes nothing new;
      - reports every PATCH failure and exits with an error when any write failed;
      - re-reads every library after writing and fails when a field differs from its expected value.

    Values written for every FILE item (folders are skipped):
      DocumentIteration    five-value cycle by position: Draft, Ready, In Review, Approved, Archived.
      LifecycleStatus      Draft and In Review -> Draft; Ready and Approved -> Published; Archived -> Archived.
                           One in twelve Published items becomes Superseded and names the previous file in
                           SupersedesDocument.
      Authoritative        true for Approved items and every second Ready item; false otherwise.
      EffectiveDate        200 to 500 days ago for Published, Superseded and Archived items.
      ReviewDate           Published items only: one in five overdue (30 to 90 days ago), the rest 60 to 300 days ahead.
      ExpirationDate       one in seven Published or Archived items expired (10 to 60 days ago); one in three of the
                           remaining items 30 to 700 days ahead; the rest left empty.
      KnowledgeOwner       person field (User Information List id of the signed-in user) and OwnerDisplayName for nine
                           in ten items. The remaining tenth has neither, so the missing-owner finding has data.
      Sensitivity          General; one in ten Confidential; one in twenty Highly Confidential.
      DocumentType         six choices cycled by base file name. A copy keeps its source's type, so exact and edited
                           copies stay in the same scope for near-duplicate detection.
      ProcessArea          Failure Analysis for names containing "Failure", Quality Escalation for "Quality",
                           otherwise General Engineering. KnowledgeCategory is Quality for "Quality", otherwise Engineering.
      ProductFamily, BusinessUnit, SourceSystem, ArtifactId
                           ArtifactId is kept when present, otherwise ART-<SITE>-<listItemId>.

    SourceSystem uses the value listed in governance-targets.json ("SharePoint Online"), the only source the policy
    approves for AIReady. The governance-computed columns (DataQualityStatus, TrustScore, AIReady, ...) are written by
    Sync-GovernanceFields.py, which runs after this script.

    Dates are written as yyyy-MM-dd, the form SharePoint stores for dateOnly columns (local midnight, 08:00Z in Pacific time).

.PARAMETER TargetsPath
    Library list. Defaults to governance-targets.json beside this script.

.PARAMETER SiteId
    Optional siteId from the targets file (for example "hr") to limit the run to one site.

.PARAMETER DryRun
    Reads the libraries and reports the changes without writing.

.EXAMPLE
    .\scripts\Seed-RichGovernanceData.ps1
#>
[CmdletBinding()]
param(
    [string]$TargetsPath = (Join-Path $PSScriptRoot 'governance-targets.json'),
    [string]$SiteId,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$iterationCycle = @('Draft', 'Ready', 'In Review', 'Approved', 'Archived')
# Per-document lifecycle pattern (repeats): most documents are approved; slots 7 and 11 are approved but flawed.
$lifecycleCycle = @('Approved', 'Approved', 'Draft', 'Approved', 'Ready', 'Approved', 'In Review', 'Approved', 'Archived', 'Approved', 'Ready', 'Approved')
$flawedSlots = @(7, 11)
$documentTypes = @('Procedure', 'Specification', 'Test Report', 'Decision Record', 'Meeting Summary', 'Technical Guide')
$productFamily = 'ApexDrive X500'
$today = [DateTime]::UtcNow.Date
$failures = [System.Collections.Generic.List[string]]::new()

$targets = Get-Content -Raw -Path $TargetsPath | ConvertFrom-Json -DateKind String
$script:GraphToken = (az account get-access-token --tenant $targets.tenantId --resource https://graph.microsoft.com --query accessToken -o tsv)
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
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Uri,
        [ValidateSet('GET', 'PATCH', 'POST')][string]$Method = 'GET',
        $Body = $null
    )
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            $parameters = @{
                Method      = $Method
                Uri         = $Uri
                Headers     = @{ Authorization = "Bearer $script:GraphToken" }
                ErrorAction = 'Stop'
            }
            if ($null -ne $Body) {
                $parameters.Body = ConvertTo-Json -InputObject $Body -Depth 6 -Compress
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
            throw "Graph $Method $Uri failed (HTTP $statusCode): $detail"
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

function Get-DateText {
    param([int]$DaysFromToday)
    return $today.AddDays($DaysFromToday).ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
}

function Get-BaseName {
    param([string]$FileName)
    $stem = [IO.Path]::GetFileNameWithoutExtension($FileName)
    return ($stem -replace '\s\((edited\s)?copy\)$', '').ToLowerInvariant()
}

function Get-NormalizedField {
    param([string]$Key, $Value)
    if ($null -eq $Value) { return $null }
    $text = [string]$Value
    if ([string]::IsNullOrEmpty($text)) { return $null }
    switch ($Key) {
        'Authoritative' { return [bool]::Parse($text) }
        'KnowledgeOwnerLookupId' { return [int]$text }
        { $_ -in 'EffectiveDate', 'ReviewDate', 'ExpirationDate' } { return $text.Substring(0, 10) }
        default { return $text }
    }
}

function Test-SameValue {
    param($Left, $Right)
    if ($null -eq $Left -or $null -eq $Right) { return ($null -eq $Left -and $null -eq $Right) }
    return ([string]$Left -ceq [string]$Right)
}

function Resolve-Library {
    param([string]$SiteGraphId, [string]$LibraryName)
    $lists = @(Get-GraphPages -Uri "https://graph.microsoft.com/v1.0/sites/$SiteGraphId/lists?`$select=id,displayName,name,list")
    $found = @($lists | Where-Object { $_.displayName -eq $LibraryName -and (Get-Prop $_.list 'template') -eq 'documentLibrary' })
    if ($found.Count -ne 1) {
        throw "Expected exactly one document library named '$LibraryName' in site $SiteGraphId; found $($found.Count)."
    }
    return $found[0]
}

function Get-LibraryFiles {
    param([string]$SiteGraphId, [string]$ListId)
    $rows = @(Get-GraphPages -Uri "https://graph.microsoft.com/v1.0/sites/$SiteGraphId/lists/$ListId/items?`$expand=fields&`$top=999")
    $files = @($rows | Where-Object {
            (Get-Prop $_.fields 'ContentType') -ne 'Folder' -and -not [string]::IsNullOrEmpty([string](Get-Prop $_.fields 'FileLeafRef'))
        })
    return @($files | Sort-Object { ([string](Get-Prop $_.fields 'FileLeafRef')).ToLowerInvariant() })
}

function Resolve-UserLookupId {
    param([string]$SiteGraphId, [string]$UserPrincipalName)
    $rows = @(Get-GraphPages -Uri "https://graph.microsoft.com/v1.0/sites/$SiteGraphId/lists/User%20Information%20List/items?`$expand=fields&`$top=999")
    foreach ($row in $rows) {
        $fields = Get-Prop $row 'fields'
        $email = [string](Get-Prop $fields 'EMail')
        $login = [string](Get-Prop $fields 'UserName')
        $claim = [string](Get-Prop $fields 'Name')
        if ($email -ieq $UserPrincipalName -or $login -ieq $UserPrincipalName -or $claim -like "*|$UserPrincipalName") {
            return [int]$row.id
        }
    }
    return $null
}

function Build-Plan {
    param(
        [Parameter(Mandatory)][object[]]$Files,
        [Parameter(Mandatory)][string]$SiteKey,
        [Parameter(Mandatory)][string]$BusinessUnit,
        $UserLookupId,
        [Parameter(Mandatory)][string]$OwnerDisplayName,
        [Parameter(Mandatory)][string]$SourceSystem
    )
    $names = @($Files | ForEach-Object { [string](Get-Prop $_.fields 'FileLeafRef') })
    $baseNames = @($names | ForEach-Object { Get-BaseName $_ } | Sort-Object -Unique)
    $copyBaseNames = @($names | Where-Object { $_ -match '\s\((edited\s)?copy\)\.[^.]+$' } | ForEach-Object { Get-BaseName $_ })
    $rows = [System.Collections.Generic.List[object]]::new()

    # Optional named stories (core approved documents, drafts, superseded policies with their successor).
    $overridesPath = Join-Path $PSScriptRoot '..\config\lifecycle-overrides.json'
    $siteOverrides = $null
    if (Test-Path $overridesPath) {
        $siteOverrides = Get-Prop (Get-Content -Raw -Path $overridesPath | ConvertFrom-Json) $SiteKey
    }
    function Get-OverrideList([string]$Key) {
        if ($null -eq $siteOverrides) { return @() }
        $list = Get-Prop $siteOverrides $Key
        if ($null -eq $list) { return @() }
        return @($list)
    }

    # One state per document (all files of a meeting share it). Most documents are approved and clean; a defined minority
    # are drafts, in review, archived or superseded, and a few approved ones carry a governance flaw for the cleanup demo.
    $baseState = @{}
    $readyCount = 0
    $flawCount = 0
    $draftCount = 0
    for ($b = 0; $b -lt $baseNames.Count; $b++) {
        $base = $baseNames[$b]
        $slot = $b % $lifecycleCycle.Count
        $iteration = $lifecycleCycle[$slot]
        $flaw = $null
        if ($slot -in $flawedSlots) {
            $flaw = @('expired', 'noOwner', 'confidential')[$flawCount % 3]
            $flawCount++
        }
        if ((Get-OverrideList 'draft') -contains $base) { $iteration = 'Draft'; $flaw = $null }
        elseif ((Get-OverrideList 'inReview') -contains $base) { $iteration = 'In Review'; $flaw = $null }
        elseif ((Get-OverrideList 'archived') -contains $base) { $iteration = 'Archived'; $flaw = $null }
        elseif ((Get-OverrideList 'approved') -contains $base -or $copyBaseNames -contains $base) { $iteration = 'Approved'; $flaw = $null }
        $lifecycle = 'Published'
        $authoritative = $false
        $supersedesName = $null
        switch ($iteration) {
            'Draft' { $lifecycle = 'Draft' }
            'In Review' { $lifecycle = 'Draft' }
            'Archived' { $lifecycle = 'Archived' }
            'Approved' { $authoritative = $true }
            'Ready' {
                if (($readyCount % 2) -eq 0) { $authoritative = $true }
                else {
                    $lifecycle = 'Superseded'
                    $supersedesName = if ($b -gt 0) { $baseNames[$b - 1] } else { $baseNames[$baseNames.Count - 1] }
                }
                $readyCount++
            }
        }
        $draftOwnerMissing = $false
        if ($lifecycle -eq 'Draft') { $draftOwnerMissing = (($draftCount % 4) -eq 3); $draftCount++ }
        $baseState[$base] = [pscustomobject]@{
            Iteration = $iteration; Lifecycle = $lifecycle; Authoritative = $authoritative; SupersedesBase = $supersedesName
            Flaw = $flaw; NoOwner = ($flaw -eq 'noOwner' -or $draftOwnerMissing)
        }
    }
    # A superseded policy keeps its history; its approved successor records what it supersedes.
    foreach ($story in (Get-OverrideList 'superseded')) {
        $old = [string](Get-Prop $story 'old')
        $by = [string](Get-Prop $story 'by')
        if ($baseState.ContainsKey($old) -and $baseState.ContainsKey($by)) {
            $baseState[$old] = [pscustomobject]@{ Iteration = 'Archived'; Lifecycle = 'Superseded'; Authoritative = $false; SupersedesBase = $null; Flaw = $null; NoOwner = $false }
            $baseState[$by] = [pscustomobject]@{ Iteration = 'Approved'; Lifecycle = 'Published'; Authoritative = $true; SupersedesBase = $old; Flaw = $null; NoOwner = $false }
        }
    }
    $nameByBase = @{}
    for ($n = 0; $n -lt $names.Count; $n++) {
        $key = Get-BaseName $names[$n]
        if (-not $nameByBase.ContainsKey($key) -or $names[$n] -notmatch '\s\((edited\s)?copy\)\.[^.]+$') { $nameByBase[$key] = $names[$n] }
    }

    for ($i = 0; $i -lt $Files.Count; $i++) {
        $name = $names[$i]
        $base = Get-BaseName $name
        $state = $baseState[$base]
        $iteration = $state.Iteration
        $lifecycle = $state.Lifecycle
        $authoritative = $state.Authoritative
        $flaw = $state.Flaw
        $supersedes = if ($state.SupersedesBase -and $nameByBase.ContainsKey($state.SupersedesBase)) { $nameByBase[$state.SupersedesBase] } else { $null }
        $hasOwner = -not $state.NoOwner
        # A stray copy is never the approved, authoritative document: keep it Draft so it cannot reach the agent.
        if ($name -match '\s\((edited\s)?copy\)\.[^.]+$') {
            $iteration = 'Draft'
            $lifecycle = 'Draft'
            $authoritative = $false
            $supersedes = $null
            $flaw = $null
        }
        $sensitivity = 'General'
        if ($flaw -eq 'confidential') { $sensitivity = $(if ((($flawCount + $i) % 2) -eq 0) { 'Confidential' } else { 'Highly Confidential' }) }
        $existingArtifact = [string](Get-Prop $Files[$i].fields 'ArtifactId')
        $artifactId = if ($existingArtifact) { $existingArtifact } else { "ART-$($SiteKey.ToUpperInvariant())-$($Files[$i].id)" }
        $rows.Add([pscustomobject]@{
                Index             = $i
                Id                = [string]$Files[$i].id
                Name              = $name
                Iteration         = $iteration
                Lifecycle         = $lifecycle
                Authoritative     = $authoritative
                Supersedes        = $supersedes
                Effective         = $null
                Review            = $null
                Expiration        = $null
                Expired           = $false
                Flaw              = $flaw
                HasOwner          = $hasOwner
                Sensitivity       = $sensitivity
                DocumentType      = $documentTypes[[Array]::IndexOf($baseNames, (Get-BaseName $name)) % $documentTypes.Count]
                ProcessArea       = $(
                    if ($name -match 'Failure') { 'Failure Analysis' }
                    elseif ($name -match 'Quality') { 'Quality Escalation' }
                    else { @('Failure Analysis', 'Quality Escalation', 'General Engineering')[[Array]::IndexOf($baseNames, (Get-BaseName $name)) % 3] }
                )
                KnowledgeCategory = $(if ($name -match 'Quality') { 'Quality' } else { @('Quality', 'Engineering')[[Array]::IndexOf($baseNames, (Get-BaseName $name)) % 2] })
                ArtifactId        = $artifactId
            })
    }

    # Expiry: only documents flagged 'expired' and archived documents are past expiry; a third of the rest carry a future date.
    $expIndex = 0
    foreach ($row in $rows) {
        if ($row.Flaw -eq 'expired' -or $row.Lifecycle -eq 'Archived') {
            $row.Expiration = Get-DateText (-(10 + (($expIndex * 11) % 51)))
            $row.Expired = $true
            $expIndex++
        }
    }
    $otherIndex = 0
    foreach ($row in $rows) {
        if ($row.Expired) { continue }
        if (($otherIndex % 3) -eq 1) { $row.Expiration = Get-DateText (30 + (($otherIndex * 19) % 671)) }
        $otherIndex++
    }

    $reviewIndex = 0
    foreach ($row in $rows) {
        if ($row.Lifecycle -eq 'Published') {
            # Approved documents are reviewed on schedule; published "Ready" ones are the ones that slip past review.
            if ($row.Iteration -ne 'Approved' -and (($reviewIndex % 2) -eq 0)) { $row.Review = Get-DateText (-(30 + (($reviewIndex * 7) % 61))) }
            else { $row.Review = Get-DateText (60 + (($reviewIndex * 13) % 241)) }
            $reviewIndex++
        }
        if ($row.Lifecycle -in 'Published', 'Superseded', 'Archived') {
            $row.Effective = Get-DateText (-(200 + (($row.Index * 37) % 301)))
        }
    }

    $plan = [System.Collections.Generic.List[object]]::new()
    foreach ($row in $rows) {
        $ownerLookup = if ($row.HasOwner -and $null -ne $UserLookupId) { [int]$UserLookupId } else { $null }
        $ownerName = if ($row.HasOwner) { $OwnerDisplayName } else { $null }
        $expected = [ordered]@{
            DocumentIteration      = $row.Iteration
            LifecycleStatus        = $row.Lifecycle
            Authoritative          = $row.Authoritative
            EffectiveDate          = $row.Effective
            ReviewDate             = $row.Review
            ExpirationDate         = $row.Expiration
            SupersedesDocument     = $row.Supersedes
            KnowledgeOwnerLookupId = $ownerLookup
            OwnerDisplayName       = $ownerName
            Sensitivity            = $row.Sensitivity
            DocumentType           = $row.DocumentType
            ProcessArea            = $row.ProcessArea
            KnowledgeCategory      = $row.KnowledgeCategory
            ProductFamily          = $productFamily
            BusinessUnit           = $BusinessUnit
            SourceSystem           = $SourceSystem
            ArtifactId             = $row.ArtifactId
        }
        $plan.Add([pscustomobject]@{
                Id        = $row.Id
                Name      = $row.Name
                Iteration = $row.Iteration
                Lifecycle = $row.Lifecycle
                Expected  = $expected
            })
    }
    $duplicateNames = @($names | Group-Object | Where-Object Count -gt 1)
    if ($duplicateNames.Count -gt 0) {
        throw "File names are not unique within the library: $(($duplicateNames | ForEach-Object Name) -join ', ')."
    }
    $duplicateArtifacts = @($plan | Group-Object { $_.Expected.ArtifactId } | Where-Object Count -gt 1)
    if ($duplicateArtifacts.Count -gt 0) {
        throw "ArtifactId values are not unique within the library: $(($duplicateArtifacts | ForEach-Object Name) -join ', ')."
    }
    return $plan.ToArray()
}

function Get-PlanChanges {
    param($PlanItem, $Fields)
    $changes = [ordered]@{}
    foreach ($key in $PlanItem.Expected.Keys) {
        if ($null -eq $PlanItem.Expected[$key]) { continue }
        $current = Get-NormalizedField -Key $key -Value (Get-Prop $Fields $key)
        if (-not (Test-SameValue $current $PlanItem.Expected[$key])) {
            $changes[$key] = $PlanItem.Expected[$key]
        }
    }
    return $changes
}

function Write-Distribution {
    param($Plan)
    $iterations = @($iterationCycle | ForEach-Object { $iteration = $_; "$iteration=$(@($Plan | Where-Object Iteration -eq $iteration).Count)" })
    $lifecycles = @(@('Draft', 'Published', 'Superseded', 'Archived') | ForEach-Object { $status = $_; "$status=$(@($Plan | Where-Object Lifecycle -eq $status).Count)" })
    Write-Host "    iterations: $($iterations -join ', ')"
    Write-Host "    lifecycle:  $($lifecycles -join ', ')"
}

function Invoke-LibrarySeed {
    param(
        [string]$SiteKey,
        [string]$SiteGraphId,
        [string]$BusinessUnit,
        $UserLookupId,
        [string]$OwnerDisplayName,
        [string]$SourceSystem,
        [string]$LibraryName
    )
    $library = Resolve-Library -SiteGraphId $SiteGraphId -LibraryName $LibraryName
    $listId = [string]$library.id
    $itemsUri = "https://graph.microsoft.com/v1.0/sites/$SiteGraphId/lists/$listId/items"
    $files = @(Get-LibraryFiles -SiteGraphId $SiteGraphId -ListId $listId)
    Write-Host "== $SiteKey / $LibraryName : $($files.Count) files" -ForegroundColor Cyan
    if ($files.Count -eq 0) { return }

    $plan = @(Build-Plan -Files $files -SiteKey $SiteKey -BusinessUnit $BusinessUnit -UserLookupId $UserLookupId -OwnerDisplayName $OwnerDisplayName -SourceSystem $SourceSystem)
    Write-Distribution -Plan $plan

    $byId = @{}
    foreach ($file in $files) { $byId[[string]$file.id] = $file.fields }
    $itemsToWrite = 0
    $fieldsToWrite = 0
    $written = 0
    foreach ($planItem in $plan) {
        $changes = Get-PlanChanges -PlanItem $planItem -Fields $byId[$planItem.Id]
        if ($changes.Count -eq 0) { continue }
        $itemsToWrite++
        $fieldsToWrite += $changes.Count
        if ($DryRun) { continue }
        try {
            Invoke-Graph -Method PATCH -Uri "$itemsUri/$($planItem.Id)/fields" -Body $changes | Out-Null
            $written++
        }
        catch {
            $failures.Add("[$SiteKey/$LibraryName] '$($planItem.Name)' (item $($planItem.Id)): $($_.Exception.Message)")
        }
    }
    Write-Host "    changes: $itemsToWrite items / $fieldsToWrite fields$(if ($DryRun) { ' (dry run, nothing written)' } else { ", written $written items" })"
    if ($DryRun) { return }

    $after = @{}
    foreach ($file in @(Get-LibraryFiles -SiteGraphId $SiteGraphId -ListId $listId)) { $after[[string]$file.id] = $file.fields }
    $mismatches = 0
    foreach ($planItem in $plan) {
        $remaining = Get-PlanChanges -PlanItem $planItem -Fields $after[$planItem.Id]
        if ($remaining.Count -gt 0) {
            $mismatches++
            $failures.Add("[$SiteKey/$LibraryName] verification: '$($planItem.Name)' still differs in $($remaining.Keys -join ', ')")
        }
    }
    Write-Host "    verified: $($plan.Count - $mismatches) of $($plan.Count) items match the expected values" -ForegroundColor Green
}

function Resolve-UserLookupForSite {
    param([string]$SiteGraphId, [string]$UserPrincipalName, [string]$SiteKey)
    $lookupId = Resolve-UserLookupId -SiteGraphId $SiteGraphId -UserPrincipalName $UserPrincipalName
    if ($null -eq $lookupId) {
        Write-Warning "$SiteKey : $UserPrincipalName is not in the User Information List. KnowledgeOwner (person) cannot be set; OwnerDisplayName is written instead."
    }
    return $lookupId
}

$me = Invoke-Graph -Uri 'https://graph.microsoft.com/v1.0/me?$select=id,displayName,userPrincipalName'
$ownerDisplayName = [string]$me.displayName
Write-Host "Signed-in owner: $ownerDisplayName ($($me.userPrincipalName))"
if ([string]::IsNullOrWhiteSpace($ownerDisplayName)) { throw 'The signed-in user has no displayName; OwnerDisplayName cannot be set.' }

$selectedSites = @($targets.sites | Where-Object { -not $SiteId -or $_.siteId -eq $SiteId })
if ($selectedSites.Count -eq 0) { throw "No site matches siteId '$SiteId' in $TargetsPath." }
foreach ($site in $selectedSites) {
    $siteGraphId = [string](Invoke-Graph -Uri "https://graph.microsoft.com/v1.0/sites/$($site.graphPath)").id
    $userLookupId = Resolve-UserLookupForSite -SiteGraphId $siteGraphId -UserPrincipalName $me.userPrincipalName -SiteKey $site.siteId
    foreach ($libraryName in @($site.libraries)) {
        Invoke-LibrarySeed -SiteKey $site.siteId -SiteGraphId $siteGraphId -BusinessUnit $site.businessUnit `
            -UserLookupId $userLookupId -OwnerDisplayName $ownerDisplayName -SourceSystem $targets.sourceSystem `
            -LibraryName $libraryName
    }
}

if ($failures.Count -gt 0) {
    foreach ($failure in $failures) { Write-Host $failure -ForegroundColor Red }
    throw "$($failures.Count) governance seed failure(s). The libraries are not fully seeded; fix the reported items and re-run."
}
if ($DryRun) {
    Write-Host 'Dry run complete. Nothing was written.' -ForegroundColor Yellow
    return
}
Write-Host 'Governance seed complete. All writes succeeded and every verified field matches.' -ForegroundColor Green
