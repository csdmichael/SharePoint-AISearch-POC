[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][uri]$AdminUrl,
    [ValidateNotNullOrEmpty()][string]$Title = 'Governed Knowledge',
    [ValidateLength(1, 128)][string]$Description = 'Document library with 27 ownership, lifecycle, classification, lineage and governance metadata columns.',
    [string]$PolicyPath = (Join-Path $PSScriptRoot '..\config\governance-policy.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($AdminUrl.Scheme -ne 'https' -or $AdminUrl.Host -notmatch '-admin\.sharepoint\.(com|us|de|cn)$' -or
    $AdminUrl.AbsolutePath -ne '/') {
    throw 'AdminUrl must be a SharePoint tenant administration URL, such as https://contoso-admin.sharepoint.com.'
}
$content = & (Join-Path $PSScriptRoot 'New-KnowledgeLibrarySiteScript.ps1') -PolicyPath $PolicyPath -LibraryName $Title
if (-not $PSCmdlet.ShouldProcess($AdminUrl, "Publish document library template '$Title' for the organization")) {
    return
}

Import-Module Microsoft.Online.SharePoint.PowerShell -ErrorAction Stop
Connect-SPOService -Url $AdminUrl.AbsoluteUri -ModernAuth $true -UseSystemBrowser $true
$existing = @(Get-SPOListDesign | Where-Object { $_.Title -eq $Title })
if ($existing.Count) {
    throw "A template named '$Title' already exists. Use a versioned title or follow the documented replacement steps."
}
$siteScript = Add-SPOSiteScript -Title "$Title library schema" -Description $Description -Content $content
Write-Host "Created site script $($siteScript.Id). Retain this ID for cleanup if list design registration fails."
$design = Add-SPOListDesign -Title $Title -Description $Description -SiteScripts @($siteScript.Id)
[pscustomobject]@{
    Title = $Title
    SiteScriptId = $siteScript.Id
    ListDesignId = $design.Id
    AdminUrl = $AdminUrl.AbsoluteUri
}
