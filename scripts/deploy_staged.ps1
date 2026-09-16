[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\deployment.json'),
    [ValidateRange(3, 30)][int]$BootstrapDocuments,
    [ValidateRange(1, 1000)][int]$FullDocuments,
    [ValidateRange(300, 8000)][int]$ChunkSize,
    [ValidateRange(0, 4000)][int]$ChunkOverlap,
    [switch]$RefreshProfile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment_config.ps1')
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$config = Import-DeploymentConfig -Path $ConfigPath
function Get-ConfigValue {
    param([Parameter(Mandatory)][string]$Path)
    return Get-DeploymentConfigValue -Config $config -Path $Path
}
if (-not $PSBoundParameters.ContainsKey('BootstrapDocuments')) { $BootstrapDocuments = Get-ConfigValue 'corpus.bootstrapDocuments' }
if (-not $PSBoundParameters.ContainsKey('FullDocuments')) { $FullDocuments = Get-ConfigValue 'corpus.expectedDocuments' }
if (-not $PSBoundParameters.ContainsKey('ChunkSize')) { $ChunkSize = Get-ConfigValue 'search.chunkSize' }
if (-not $PSBoundParameters.ContainsKey('ChunkOverlap')) { $ChunkOverlap = Get-ConfigValue 'search.chunkOverlap' }

if ($ChunkOverlap -ge $ChunkSize) {
    throw 'ChunkOverlap must be smaller than ChunkSize.'
}

$python = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.pythonExecutable')
if (-not (Test-Path $python)) {
    throw "Python environment not found at $python. Create it and install requirements.txt first."
}

function Invoke-Python {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

Push-Location $repositoryRoot
try {
    $resolvedConfigPath = (Resolve-Path $ConfigPath).Path
    $profilePath = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.profile')
    $bootstrapCorpusPath = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.bootstrapCorpus')
    $corpusPath = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.corpus')
    if ($RefreshProfile) {
        Write-Host 'Stage 0: Refreshing the Databricks source profile...'
        Invoke-Python -Arguments @('scripts\fetch_semiconductor_profile.py', '--config', $resolvedConfigPath)
    }
    if (-not (Test-Path $profilePath)) {
        throw 'No source profile is available. Rerun with -RefreshProfile.'
    }
    Invoke-Python -Arguments @(
        'scripts\fetch_semiconductor_profile.py',
        '--config', $resolvedConfigPath,
        '--validate-existing',
        $profilePath
    )

    $bootstrapSharePointState = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.bootstrapSharePointState')
    $bootstrapSearchState = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.bootstrapSearchState')
    $candidateSearchState = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.candidateSearchState')
    $bootstrapLibraryName = Get-ConfigValue 'sharePoint.bootstrapLibraryName'

    Write-Host 'Stage 1: Provisioning production and isolated bootstrap SharePoint libraries...'
    & "$PSScriptRoot\provision_sharepoint.ps1" -ConfigPath $resolvedConfigPath -SiteOnly
    & "$PSScriptRoot\provision_sharepoint.ps1" `
        -ConfigPath $resolvedConfigPath `
        -SiteOnly `
        -LibraryDisplayName $bootstrapLibraryName `
        -StatePath $bootstrapSharePointState

    Write-Host "Stage 2: Generating and validating $BootstrapDocuments bootstrap documents..."
    Invoke-Python -Arguments @(
        'scripts\generate_corpus.py',
        '--config', $resolvedConfigPath,
        '--document-count', [string]$BootstrapDocuments,
        '--output', $bootstrapCorpusPath
    )
    Invoke-Python -Arguments @(
        'scripts\validate_corpus.py',
        '--config', $resolvedConfigPath,
        '--corpus', $bootstrapCorpusPath,
        '--expected-count', [string]$BootstrapDocuments
    )

    Write-Host 'Stage 3: Uploading the isolated bootstrap corpus and creating the bootstrap index...'
    & "$PSScriptRoot\provision_sharepoint.ps1" `
        -ConfigPath $resolvedConfigPath `
        -CorpusPath $bootstrapCorpusPath `
        -ExpectedDocuments $BootstrapDocuments `
        -PruneMissingDocuments `
        -LibraryDisplayName $bootstrapLibraryName `
        -StatePath $bootstrapSharePointState
    & "$PSScriptRoot\provision_search.ps1" `
        -ConfigPath $resolvedConfigPath `
        -ChunkSize $ChunkSize `
        -ChunkOverlap $ChunkOverlap `
        -ResourceNamePrefix (Get-ConfigValue 'search.bootstrapResourceNamePrefix') `
        -SharePointStatePath $bootstrapSharePointState `
        -SearchStatePath $bootstrapSearchState `
        -RecreateIndex
    & "$PSScriptRoot\validate_search.ps1" `
        -ConfigPath $resolvedConfigPath `
        -ExpectedDocuments $BootstrapDocuments `
        -ManifestPath (Join-Path $bootstrapCorpusPath 'manifest.json') `
        -SharePointStatePath $bootstrapSharePointState `
        -SearchStatePath $bootstrapSearchState
    & "$PSScriptRoot\evaluate_search.ps1" `
        -ConfigPath $resolvedConfigPath `
        -ReportPath (Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.bootstrapSearchEvaluationReport')) `
        -SharePointStatePath $bootstrapSharePointState `
        -SearchStatePath $bootstrapSearchState `
        -MinimumSourceHitAt3 (Get-ConfigValue 'evaluation.bootstrapMinimumSourceHitAt3')
    & "$PSScriptRoot\set_search_indexer_state.ps1" `
        -ConfigPath $resolvedConfigPath `
        -SearchStatePath $bootstrapSearchState `
        -SharePointStatePath $bootstrapSharePointState `
        -Disabled $true | Out-Null

    Write-Host "Stage 4: Generating and validating the full $FullDocuments-document replacement corpus before production mutation..."
    Invoke-Python -Arguments @(
        'scripts\generate_corpus.py',
        '--config', $resolvedConfigPath,
        '--document-count', [string]$FullDocuments,
        '--output', $corpusPath
    )
    Invoke-Python -Arguments @(
        'scripts\validate_corpus.py',
        '--config', $resolvedConfigPath,
        '--corpus', $corpusPath,
        '--expected-count', [string]$FullDocuments
    )

    Write-Host 'Stage 5: Uploading the prevalidated full corpus to the production library...'
    $currentSearchState = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.searchState')
    if (Test-Path $currentSearchState) {
        & "$PSScriptRoot\set_search_indexer_state.ps1" `
            -ConfigPath $resolvedConfigPath `
            -SearchStatePath $currentSearchState `
            -Disabled $true | Out-Null
    }
    & "$PSScriptRoot\provision_sharepoint.ps1" `
        -ConfigPath $resolvedConfigPath `
        -CorpusPath $corpusPath `
        -ExpectedDocuments $FullDocuments

    $generation = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
    $candidatePrefix = "$(Get-ConfigValue 'search.resourceNamePrefix')-$generation"
    $candidateIndexName = "$candidatePrefix-$(Get-ConfigValue 'search.indexNameSuffix')"
    Write-Host "Stage 6: Building and validating candidate index $candidateIndexName without touching the current index..."
    & "$PSScriptRoot\provision_search.ps1" `
        -ConfigPath $resolvedConfigPath `
        -ChunkSize $ChunkSize `
        -ChunkOverlap $ChunkOverlap `
        -ResourceNamePrefix $candidatePrefix `
        -IndexName $candidateIndexName `
        -SearchStatePath $candidateSearchState `
        -RecreateIndex
    & "$PSScriptRoot\validate_search.ps1" `
        -ConfigPath $resolvedConfigPath `
        -ExpectedDocuments $FullDocuments `
        -SearchStatePath $candidateSearchState
    & "$PSScriptRoot\evaluate_search.ps1" `
        -ConfigPath $resolvedConfigPath `
        -ReportPath (Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.finalSearchEvaluationReport')) `
        -SearchStatePath $candidateSearchState `
        -MinimumSourceHitAt3 (Get-ConfigValue 'evaluation.minimumSourceHitAt3')

    Write-Host 'Stage 7: Atomically promoting the validated candidate through the stable Search alias...'
    & "$PSScriptRoot\promote_search_index.ps1" `
        -ConfigPath $resolvedConfigPath `
        -CandidateSearchStatePath $candidateSearchState `
        -CurrentSearchStatePath $currentSearchState
    & "$PSScriptRoot\set_search_indexer_state.ps1" `
        -ConfigPath $resolvedConfigPath `
        -SearchStatePath $currentSearchState `
        -Disabled $false | Out-Null

    [pscustomobject]@{
        status = 'completed'
        bootstrapDocuments = $BootstrapDocuments
        fullDocuments = $FullDocuments
        chunkSize = $ChunkSize
        chunkOverlap = $ChunkOverlap
        promotedAlias = Get-ConfigValue 'search.indexAliasName'
        promotedIndex = $candidateIndexName
        finalEvaluation = Resolve-DeploymentPath -RepositoryRoot $repositoryRoot -Path (Get-ConfigValue 'paths.finalSearchEvaluationReport')
    } | ConvertTo-Json
}
finally {
    Pop-Location
}