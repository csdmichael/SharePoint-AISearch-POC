[CmdletBinding()]
param(
    [string]$PolicyPath = (Join-Path $PSScriptRoot '..\config\governance-policy.json'),
    [ValidateNotNullOrEmpty()][string]$LibraryName = 'Governed Knowledge',
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$policy = Get-Content -LiteralPath $PolicyPath -Raw | ConvertFrom-Json
$columns = @($policy.sharePointColumns)
if (-not $columns.Count) { throw 'The policy must define sharePointColumns.' }
$names = @($columns | ForEach-Object { $_.name })
if (@($names | Sort-Object -Unique).Count -ne $names.Count) {
    throw 'The policy contains duplicate column internal names.'
}

$subactions = @(
    [ordered]@{ verb = 'setDescription'; description = 'Knowledge documents with ownership, lifecycle, classification, lineage and governance metadata.' }
)
foreach ($column in $columns) {
    if ($column.name -notmatch '^[A-Za-z][A-Za-z0-9_]{0,31}$') {
        throw "Invalid column internal name: $($column.name)"
    }
    $types = @('text', 'choice', 'dateTime', 'personOrGroup', 'boolean', 'number') |
        Where-Object { $column.PSObject.Properties.Name -contains $_ }
    if (@($types).Count -ne 1) { throw "Unsupported or ambiguous type for $($column.name)." }
    $type = @($types)[0]
    $xml = [xml]'<Field />'
    $field = $xml.DocumentElement
    # Stable IDs prevent duplicate fields when SharePoint reapplies the site script.
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $hash.ComputeHash([Text.Encoding]::UTF8.GetBytes("governed-knowledge-column:$($column.name)"))
    }
    finally { $hash.Dispose() }
    $id = [Guid]::new([byte[]]$bytes[0..15])
    $attributes = [ordered]@{
        ID = "{$id}"
        Name = $column.name
        StaticName = $column.name
        DisplayName = $column.displayName
        Description = $column.description
        Required = ([string][bool]($column.PSObject.Properties.Name -contains 'required' -and $column.required)).ToUpperInvariant()
        Indexed = ([string][bool]$column.indexed).ToUpperInvariant()
        EnforceUniqueValues = ([string][bool]$column.enforceUniqueValues).ToUpperInvariant()
    }
    switch ($type) {
        'text' {
            if ($column.text.allowMultipleLines) {
                $attributes.Type = 'Note'
                $attributes.NumLines = [string]$column.text.linesForEditing
                $attributes.RichText = 'FALSE'
                $attributes.AppendOnly = ([string][bool]$column.text.appendChangesToExistingText).ToUpperInvariant()
                $attributes.UnlimitedLengthInDocumentLibrary = 'TRUE'
            }
            else {
                $attributes.Type = 'Text'
                $attributes.MaxLength = [string]$column.text.maxLength
            }
        }
        'choice' {
            $attributes.Type = 'Choice'
            $attributes.Format = 'Dropdown'
            $attributes.FillInChoice = ([string][bool]$column.choice.allowTextEntry).ToUpperInvariant()
            $choices = $xml.CreateElement('CHOICES')
            foreach ($value in $column.choice.choices) {
                $choice = $xml.CreateElement('CHOICE')
                $choice.InnerText = [string]$value
                $null = $choices.AppendChild($choice)
            }
            $null = $field.AppendChild($choices)
        }
        'dateTime' {
            $attributes.Type = 'DateTime'
            $attributes.Format = if ($column.dateTime.format -eq 'dateOnly') { 'DateOnly' } else { 'DateTime' }
        }
        'personOrGroup' {
            if ($column.personOrGroup.allowMultipleSelection) {
                throw "Multiple-selection people fields are not supported: $($column.name)"
            }
            $attributes.Type = 'User'
            $attributes.List = 'UserInfo'
            $attributes.ShowField = 'ImnName'
            $attributes.UserSelectionMode = if ($column.personOrGroup.chooseFromType -eq 'peopleOnly') { 'PeopleOnly' } else { 'PeopleAndGroups' }
        }
        'boolean' { $attributes.Type = 'Boolean' }
        'number' {
            $attributes.Type = 'Number'
            $attributes.Min = [string]$column.number.minimum
            $attributes.Max = [string]$column.number.maximum
            $attributes.Decimals = if ($column.number.decimalPlaces -eq 'none') { '0' } else { 'Automatic' }
        }
    }
    foreach ($attribute in $attributes.GetEnumerator()) {
        $field.SetAttribute($attribute.Key, [string]$attribute.Value)
    }
    $defaultValue = if ($column.PSObject.Properties.Name -contains 'defaultValue') {
        [string]$column.defaultValue
    }
    else {
        switch ($column.name) {
        'LifecycleStatus' {
            if ($column.choice.choices -notcontains 'Draft') { throw 'LifecycleStatus must allow Draft.' }
            'Draft'
        }
        'Authoritative' { '0' }
        'AIReady' { '0' }
        }
    }
    if ($null -ne $defaultValue -and $type -eq 'choice' -and $column.choice.choices -notcontains $defaultValue) {
        throw "$($column.name) default value '$defaultValue' is not in the choice list."
    }
    if ($null -ne $defaultValue) {
        $default = $xml.CreateElement('Default')
        $default.InnerText = $defaultValue
        $null = $field.AppendChild($default)
    }
    $subactions += [ordered]@{
        verb = 'addSPFieldXml'
        schemaXml = $field.OuterXml
        addToDefaultView = $false
    }
}
$ownerFields = @(
    'KnowledgeOwner', 'LifecycleStatus', 'DocumentIteration', 'Authoritative', 'ReviewDate',
    'DocumentType', 'ProductFamily', 'ProcessArea', 'Sensitivity', 'AIReady'
) | Where-Object { $names -contains $_ }
$subactions += [ordered]@{
    verb = 'addSPView'; name = 'Knowledge Documents'
    viewFields = @('DocIcon', 'LinkFilename') + @($ownerFields) + @('Modified', 'Editor')
    query = ''; rowLimit = 30; isPaged = $true; makeDefault = $true
}
$subactions += [ordered]@{
    verb = 'addSPView'; name = 'All Metadata'
    viewFields = @('DocIcon', 'LinkFilename') + $names + @('Modified', 'Editor')
    query = ''; rowLimit = 30; isPaged = $true; makeDefault = $false
}
$siteScript = [ordered]@{
    '$schema' = 'https://developer.microsoft.com/json-schemas/sp/site-design-script-actions.schema.json'
    actions = @([ordered]@{
        verb = 'createSPList'
        listName = $LibraryName
        templateType = 101
        subactions = $subactions
    })
}
$json = $siteScript | ConvertTo-Json -Depth 20
if ($OutputPath) {
    $json | Set-Content -LiteralPath $OutputPath -Encoding utf8
}
$json
