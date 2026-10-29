[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$generator = Join-Path $root 'scripts\New-KnowledgeLibrarySiteScript.ps1'
$publisher = Join-Path $root 'scripts\Publish-KnowledgeLibraryTemplate.ps1'
$policyPath = Join-Path $root 'config\governance-policy.json'
$exportPath = Join-Path $root 'config\knowledge-library.site-script.json'
$testState = @{
    Assertions = 0
    Calls = [Collections.Generic.List[string]]::new()
    ExistingDesigns = @()
    RegistrationFails = $false
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    $testState.Assertions++
    if (-not $Condition) { throw "Assertion failed: $Message" }
}
function Assert-Throws {
    param([scriptblock]$Action, [string]$Pattern)
    $caught = $null
    try { & $Action | Out-Null } catch { $caught = $_ }
    Assert-True ($null -ne $caught -and $caught.Exception.Message -match $Pattern) "Expected error matching $Pattern"
}

$json = & $generator
$template = $json | ConvertFrom-Json
$policy = Get-Content -LiteralPath $policyPath -Raw | ConvertFrom-Json
Assert-True ($template.actions.Count -eq 1) 'One library action'
$library = $template.actions[0]
Assert-True ($policy.sharePointColumns.Count -eq 28) 'All 28 additional columns are defined'
Assert-True ($library.verb -eq 'createSPList' -and $library.templateType -eq 101) 'Document library, not generic list'
$fields = @($library.subactions | Where-Object verb -eq 'addSPFieldXml')
Assert-True ($fields.Count -eq $policy.sharePointColumns.Count) 'Every policy column is exported'
$byName = @{}
$ids = @()
foreach ($action in $fields) {
    $field = ([xml]$action.schemaXml).Field
    $byName[$field.Name] = $field
    $ids += [Guid]$field.ID
    Assert-True (-not $action.addToDefaultView) 'Views are defined explicitly'
}
Assert-True (@($ids | Sort-Object -Unique).Count -eq $policy.sharePointColumns.Count) 'Unique valid field IDs'
foreach ($column in $policy.sharePointColumns) {
    $field = $byName[$column.name]
    Assert-True ($null -ne $field) "Internal name $($column.name)"
    Assert-True ($field.StaticName -eq $column.name -and $field.DisplayName -eq $column.displayName) 'Names match policy'
    $isRequired = $column.PSObject.Properties.Name -contains 'required' -and [bool]$column.required
    $expectedRequired = ([string]$isRequired).ToUpperInvariant()
    Assert-True ($field.Description -eq $column.description -and $field.Required -eq $expectedRequired) 'Descriptions and required field settings'
    Assert-True ($field.Indexed -eq ([string]$column.indexed).ToUpperInvariant()) 'Indexing preserved'
    Assert-True ($field.EnforceUniqueValues -eq ([string]$column.enforceUniqueValues).ToUpperInvariant()) 'Uniqueness preserved'
    $type = @('text', 'choice', 'dateTime', 'personOrGroup', 'boolean', 'number') |
        Where-Object { $column.PSObject.Properties.Name -contains $_ }
    switch ($type) {
        'text' {
            if ($column.text.allowMultipleLines) {
                Assert-True ($field.Type -eq 'Note' -and $field.RichText -eq 'FALSE' -and
                    $field.NumLines -eq [string]$column.text.linesForEditing -and
                    $field.AppendOnly -eq 'FALSE' -and $field.UnlimitedLengthInDocumentLibrary -eq 'TRUE') 'Plain multiline field'
            }
            else {
                Assert-True ($field.Type -eq 'Text' -and $field.MaxLength -eq [string]$column.text.maxLength) 'Text length preserved'
            }
        }
        'choice' {
            Assert-True ($field.Type -eq 'Choice' -and $field.FillInChoice -eq 'FALSE' -and
                $field.Format -eq 'Dropdown') 'Choice constraints preserved'
            Assert-True ((@($field.CHOICES.CHOICE) | ConvertTo-Json -Compress) -ceq
                (@($column.choice.choices) | ConvertTo-Json -Compress)) 'Exact ordered choice values'
        }
        'dateTime' {
            $format = if ($column.dateTime.format -eq 'dateOnly') { 'DateOnly' } else { 'DateTime' }
            Assert-True ($field.Type -eq 'DateTime' -and $field.Format -eq $format) 'Date format preserved'
        }
        'personOrGroup' {
            Assert-True ($field.Type -eq 'User' -and $field.List -eq 'UserInfo' -and
                $field.UserSelectionMode -eq 'PeopleAndGroups') 'Owner is a person/group field'
        }
        'boolean' { Assert-True ($field.Type -eq 'Boolean') 'Boolean type preserved' }
        'number' {
            Assert-True ($field.Type -eq 'Number' -and $field.Min -eq '0' -and
                $field.Max -eq '100' -and $field.Decimals -eq '0') 'Trust score bounds preserved'
        }
    }
}
Assert-True ($byName.LifecycleStatus.Default -eq 'Draft') 'Draft by default'
Assert-True ($byName.DocumentIteration.Default -eq 'Draft' -and $byName.DocumentIteration.Required -eq 'TRUE') 'Document iteration defaults and required flag'
Assert-True ($byName.Authoritative.Default -eq '0' -and $byName.AIReady.Default -eq '0') 'No automatic trust'
$views = @($library.subactions | Where-Object verb -eq 'addSPView')
Assert-True ($views.Count -eq 2 -and $views[0].makeDefault -and -not $views[1].makeDefault) 'Owner and all-metadata views'
foreach ($name in $byName.Keys) {
    Assert-True ($views[1].viewFields -contains $name) "All Metadata contains $name"
}
$second = & $generator -LibraryName 'Another Library' | ConvertFrom-Json
Assert-True ($second.actions[0].listName -eq 'Another Library') 'Custom library name'
$secondFields = @($second.actions[0].subactions | Where-Object verb -eq 'addSPFieldXml')
Assert-True (($fields | ConvertTo-Json -Depth 10 -Compress) -ceq
    ($secondFields | ConvertTo-Json -Depth 10 -Compress)) 'Field IDs and schema stable across libraries'
$export = Get-Content -LiteralPath $exportPath -Raw | ConvertFrom-Json
Assert-True (($export | ConvertTo-Json -Depth 20 -Compress) -ceq
    ($template | ConvertTo-Json -Depth 20 -Compress)) 'Checked-in template matches current policy'

$temporaryPolicy = Join-Path ([IO.Path]::GetTempPath()) ("knowledge-template-test-{0}.json" -f [Guid]::NewGuid())
try {
    $policy.sharePointColumns[0].displayName = 'Artifact & "ID" <value>'
    $policy.sharePointColumns[0].description = 'A < B & C > D'
    $policy | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporaryPolicy
    $escaped = & $generator -PolicyPath $temporaryPolicy | ConvertFrom-Json
    $escapedField = ([xml]$escaped.actions[0].subactions[1].schemaXml).Field
    Assert-True ($escapedField.DisplayName -eq $policy.sharePointColumns[0].displayName -and
        $escapedField.Description -eq $policy.sharePointColumns[0].description) 'XML escaping round-trips'
    $policy.sharePointColumns[1].name = $policy.sharePointColumns[0].name
    $policy | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporaryPolicy
    Assert-Throws { & $generator -PolicyPath $temporaryPolicy } 'duplicate'
    $policy = Get-Content -LiteralPath $policyPath -Raw | ConvertFrom-Json
    $policy.sharePointColumns[0].PSObject.Properties.Remove('text')
    $policy | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporaryPolicy
    Assert-Throws { & $generator -PolicyPath $temporaryPolicy } 'Unsupported'
    Assert-Throws { & $generator -PolicyPath "$temporaryPolicy.missing" } 'does not exist'
}
finally {
    if (Test-Path -LiteralPath $temporaryPolicy) { Remove-Item -LiteralPath $temporaryPolicy }
}

function Import-Module { param($Name, $ErrorAction) $testState.Calls.Add("Import:$Name") }
function Connect-SPOService {
    param($Url, $ModernAuth, $UseSystemBrowser)
    Assert-True ($ModernAuth -and $UseSystemBrowser) 'Modern authentication uses the system browser'
    $testState.Calls.Add("Connect:$Url")
}
function Get-SPOListDesign { $testState.ExistingDesigns }
function Add-SPOSiteScript {
    param($Title, $Description, $Content)
    $testState.Calls.Add('AddSiteScript')
    Assert-True ($Description.Length -le 64) 'Site script description fits the SharePoint limit'
    Assert-True (($Content | ConvertFrom-Json).actions[0].templateType -eq 101) 'Publisher registers library schema'
    [pscustomobject]@{ Id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' }
}
function Add-SPOListDesign {
    param($Title, $Description, $SiteScripts)
    $testState.Calls.Add('AddListDesign')
    Assert-True ($SiteScripts.Count -eq 1 -and $SiteScripts[0] -eq 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') 'Design references created script'
    if ($testState.RegistrationFails) { throw 'Registration failed' }
    [pscustomobject]@{ Id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb' }
}
& $publisher -AdminUrl https://contoso-admin.sharepoint.com -WhatIf
Assert-True ($testState.Calls.Count -eq 0) 'WhatIf performs no authentication or tenant changes'
Assert-Throws { & $publisher -AdminUrl https://contoso.sharepoint.com } 'administration URL'
Assert-Throws { & $publisher -AdminUrl https://contoso-admin.sharepoint.com -Description ('x' * 65) } 'Description'
$result = & $publisher -AdminUrl https://contoso-admin.sharepoint.com -Confirm:$false
Assert-True ($result.ListDesignId -eq 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb' -and
    $result.SiteScriptId -eq 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') 'Publisher returns management IDs'
Assert-True (($testState.Calls -join ',') -eq
    'Import:Microsoft.Online.SharePoint.PowerShell,Connect:https://contoso-admin.sharepoint.com/,AddSiteScript,AddListDesign') 'Publication order'
$testState.Calls.Clear()
$testState.ExistingDesigns = @([pscustomobject]@{ Title = 'Governed Knowledge' })
Assert-Throws { & $publisher -AdminUrl https://contoso-admin.sharepoint.com -Confirm:$false } 'already exists'
Assert-True (-not $testState.Calls.Contains('AddSiteScript')) 'Duplicate templates do not mutate tenant'
$testState.ExistingDesigns = @()
$testState.RegistrationFails = $true
Assert-Throws { & $publisher -AdminUrl https://contoso-admin.sharepoint.com -Confirm:$false } 'Registration failed'
Write-Host "Passed $($testState.Assertions) assertions (offline; no SharePoint connection)."
