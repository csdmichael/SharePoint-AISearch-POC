[CmdletBinding()]
param(
    [ValidateRange(3, 30)][int]$BootstrapDocuments = 6,
    [ValidateRange(100, 1000)][int]$FullDocuments = 100,
    [ValidateRange(300, 8000)][int]$ChunkSize = 512,
    [ValidateRange(0, 4000)][int]$ChunkOverlap = 128,
    [switch]$RefreshProfile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($ChunkOverlap -ge $ChunkSize) {
    throw 'ChunkOverlap must be smaller than ChunkSize.'
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
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
    if ($RefreshProfile) {
        Write-Host 'Stage 0: Refreshing the Databricks source profile...'
        Invoke-Python -Arguments @('scripts\fetch_semiconductor_profile.py')
    }
    if (-not (Test-Path 'data\semiconductor_profile.json')) {
        throw 'No source profile is available. Rerun with -RefreshProfile.'
    }
    Invoke-Python -Arguments @(
        'scripts\fetch_semiconductor_profile.py',
        '--validate-existing',
        'data\semiconductor_profile.json'
    )

    $bootstrapSharePointState = Join-Path $repositoryRoot '.state\sharepoint-bootstrap.json'
    $bootstrapSearchState = Join-Path $repositoryRoot '.state\search-bootstrap.json'
    $candidateSearchState = Join-Path $repositoryRoot '.state\search-candidate.json'
    $bootstrapLibraryName = 'Semiconductor Knowledge Bootstrap'

    Write-Host 'Stage 1: Provisioning production and isolated bootstrap SharePoint libraries...'
    & "$PSScriptRoot\provision_sharepoint.ps1" -SiteOnly
    & "$PSScriptRoot\provision_sharepoint.ps1" `
        -SiteOnly `
        -LibraryDisplayName $bootstrapLibraryName `
        -StatePath $bootstrapSharePointState

    Write-Host "Stage 2: Generating and validating $BootstrapDocuments bootstrap documents..."
    Invoke-Python -Arguments @(
        'scripts\generate_corpus.py',
        '--document-count', [string]$BootstrapDocuments,
        '--output', 'corpus-bootstrap'
    )
    Invoke-Python -Arguments @(
        'scripts\validate_corpus.py',
        '--corpus', 'corpus-bootstrap',
        '--expected-count', [string]$BootstrapDocuments
    )

    Write-Host 'Stage 3: Uploading the isolated bootstrap corpus and creating the bootstrap index...'
    & "$PSScriptRoot\provision_sharepoint.ps1" `
        -CorpusPath (Join-Path $repositoryRoot 'corpus-bootstrap') `
        -ExpectedDocuments $BootstrapDocuments `
        -PruneMissingDocuments `
        -LibraryDisplayName $bootstrapLibraryName `
        -StatePath $bootstrapSharePointState
    & "$PSScriptRoot\provision_search.ps1" `
        -ChunkSize $ChunkSize `
        -ChunkOverlap $ChunkOverlap `
        -ResourceNamePrefix 'semiconductor-bootstrap' `
        -SharePointStatePath $bootstrapSharePointState `
        -SearchStatePath $bootstrapSearchState `
        -RecreateIndex
    & "$PSScriptRoot\validate_search.ps1" `
        -ExpectedDocuments $BootstrapDocuments `
        -ManifestPath (Join-Path $repositoryRoot 'corpus-bootstrap\manifest.json') `
        -SharePointStatePath $bootstrapSharePointState `
        -SearchStatePath $bootstrapSearchState
    & "$PSScriptRoot\evaluate_search.ps1" `
        -ReportPath (Join-Path $repositoryRoot '.state\search-evaluation-bootstrap.json') `
        -SharePointStatePath $bootstrapSharePointState `
        -SearchStatePath $bootstrapSearchState `
        -MinimumSourceHitAt3 0.8
    & "$PSScriptRoot\set_search_indexer_state.ps1" `
        -SearchStatePath $bootstrapSearchState `
        -SharePointStatePath $bootstrapSharePointState `
        -Disabled $true | Out-Null

    Write-Host "Stage 4: Generating and validating the full $FullDocuments-document replacement corpus before production mutation..."
    Invoke-Python -Arguments @(
        'scripts\generate_corpus.py',
        '--document-count', [string]$FullDocuments,
        '--output', 'corpus'
    )
    Invoke-Python -Arguments @(
        'scripts\validate_corpus.py',
        '--corpus', 'corpus',
        '--expected-count', [string]$FullDocuments
    )

    Write-Host 'Stage 5: Uploading the prevalidated full corpus to the production library...'
    $currentSearchState = Join-Path $repositoryRoot '.state\search.json'
    if (Test-Path $currentSearchState) {
        & "$PSScriptRoot\set_search_indexer_state.ps1" `
            -SearchStatePath $currentSearchState `
            -Disabled $true | Out-Null
    }
    & "$PSScriptRoot\provision_sharepoint.ps1" `
        -CorpusPath (Join-Path $repositoryRoot 'corpus') `
        -ExpectedDocuments $FullDocuments

    $generation = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
    $candidatePrefix = "semiconductor-$generation"
    $candidateIndexName = "$candidatePrefix-knowledge-chunks"
    Write-Host "Stage 6: Building and validating candidate index $candidateIndexName without touching the current index..."
    & "$PSScriptRoot\provision_search.ps1" `
        -ChunkSize $ChunkSize `
        -ChunkOverlap $ChunkOverlap `
        -ResourceNamePrefix $candidatePrefix `
        -IndexName $candidateIndexName `
        -SearchStatePath $candidateSearchState `
        -RecreateIndex
    & "$PSScriptRoot\validate_search.ps1" `
        -ExpectedDocuments $FullDocuments `
        -SearchStatePath $candidateSearchState
    & "$PSScriptRoot\evaluate_search.ps1" `
        -ReportPath (Join-Path $repositoryRoot '.state\search-evaluation-final.json') `
        -SearchStatePath $candidateSearchState `
        -MinimumSourceHitAt3 0.9

    Write-Host 'Stage 7: Atomically promoting the validated candidate through the stable Search alias...'
    & "$PSScriptRoot\promote_search_index.ps1" `
        -CandidateSearchStatePath $candidateSearchState `
        -CurrentSearchStatePath (Join-Path $repositoryRoot '.state\search.json')
    & "$PSScriptRoot\set_search_indexer_state.ps1" `
        -SearchStatePath (Join-Path $repositoryRoot '.state\search.json') `
        -Disabled $false | Out-Null

    [pscustomobject]@{
        status = 'completed'
        bootstrapDocuments = $BootstrapDocuments
        fullDocuments = $FullDocuments
        chunkSize = $ChunkSize
        chunkOverlap = $ChunkOverlap
        promotedAlias = 'semiconductor-knowledge'
        promotedIndex = $candidateIndexName
        finalEvaluation = (Join-Path $repositoryRoot '.state\search-evaluation-final.json')
    } | ConvertTo-Json
}
finally {
    Pop-Location
}