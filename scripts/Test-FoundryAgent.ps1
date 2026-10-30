<#
.SYNOPSIS
    End-to-end test of the trusted knowledge Foundry agent against the live search indexes.

.DESCRIPTION
    Asks the agent one question per knowledge hub, including questions answered only by meeting transcripts. For every
    question it checks that the agent called the knowledge base, returned text, and cited a document from the expected
    SharePoint site. It exits with code 1 when any check fails.

.PARAMETER StatePath
    Foundry agent state written by provision_foundry_agent.ps1. Supplies the project endpoint and agent name.

.EXAMPLE
    .\scripts\Test-FoundryAgent.ps1
#>
[CmdletBinding()]
param(
    [string]$StatePath = (Join-Path $PSScriptRoot '..\.state\trusted-foundry-agent.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$state = Get-Content -Raw -Path $StatePath | ConvertFrom-Json
$token = (az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv).Trim()
if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'Could not get a Foundry token. Run az login and retry.' }
$authHeader = 'Bearer ' + $token
$headers = @{ Authorization = $authHeader; 'Content-Type' = 'application/json' }
$project = $state.projectEndpoint.TrimEnd('/')

$cases = @(
    @{ Hub = 'hr'; Site = 'hrknowledgehub'; Question = 'How many weeks of paid parental leave does the primary caregiver get, and which document says so?' },
    @{ Hub = 'hr'; Site = 'hrknowledgehub'; Question = 'In the 401(k) plan vendor check-in meeting, what did the team say about the auto-enrollment opt-out rate?' },
    @{ Hub = 'manufacturing'; Site = 'manufacturingknowledgehub'; Question = 'What did the Line 3 yield improvement tollgate meeting say about seal leak defects?' },
    @{ Hub = 'manufacturing'; Site = 'manufacturingknowledgehub'; Question = 'What does the changeover standard operating procedure cover?' },
    @{ Hub = 'sales'; Site = 'salesmarketingknowledgehub'; Question = 'In the discovery call coaching session, what should happen before scheduling a demo?' },
    @{ Hub = 'sales'; Site = 'salesmarketingknowledgehub'; Question = 'What does the discovery call guide say about qualifying an economic buyer?' },
    # Draft-only content: the agent must not cite it.
    @{ Hub = 'sales (draft must stay hidden)'; Forbidden = 'competitive-win-loss-debrief'; Question = 'What did the competitive win-loss debrief meeting conclude?' },
    @{ Hub = 'sales (draft must stay hidden)'; Forbidden = 'proposal-and-pricing-template-guide'; Question = 'Summarize the proposal and pricing template guide.' }
)

$failures = 0
foreach ($case in $cases) {
    Write-Host "`n[$($case.Hub)] $($case.Question)" -ForegroundColor Cyan
    try {
        $conversation = Invoke-RestMethod -Method POST -Uri "$project/openai/v1/conversations" -Headers $headers -Body '{}'
        $body = @{
            conversation    = $conversation.id
            input           = $case.Question
            agent_reference = @{ type = 'agent_reference'; name = $state.agentName }
        } | ConvertTo-Json -Depth 6
        $response = Invoke-RestMethod -Method POST -Uri "$project/openai/v1/responses" -Headers $headers -Body $body -TimeoutSec 180
    }
    catch {
        Write-Host "  FAIL request error: $($_.Exception.Message)" -ForegroundColor Red
        $failures++
        continue
    }
    $json = $response | ConvertTo-Json -Depth 100 -Compress
    $text = (@($response.output | ForEach-Object {
                if ($_.PSObject.Properties.Name -contains 'content') { @($_.content) | Where-Object { $_.type -eq 'output_text' } | ForEach-Object { $_.text } }
            })) -join "`n"
    $calledKnowledge = $json -match 'knowledge_base_retrieve'
    $citedSite = if ($case.ContainsKey('Site')) { $text -match [regex]::Escape("/sites/$($case.Site)/") } else { $true }
    $leaked = $case.ContainsKey('Forbidden') -and (($text -match [regex]::Escape($case.Forbidden)) -or ($json -match [regex]::Escape($case.Forbidden)))
    $checks = [ordered]@{ 'returned text' = -not [string]::IsNullOrWhiteSpace($text); 'called knowledge base' = $calledKnowledge }
    if ($case.ContainsKey('Site')) { $checks["cited $($case.Site)"] = $citedSite }
    if ($case.ContainsKey('Forbidden')) { $checks["did not surface $($case.Forbidden)"] = -not $leaked }
    foreach ($check in $checks.GetEnumerator()) {
        $label = if ($check.Value) { 'PASS' } else { 'FAIL'; $failures++ }
        Write-Host ("  [{0}] {1}" -f $label, $check.Key) -ForegroundColor $(if ($check.Value) { 'Green' } else { 'Red' })
    }
    $preview = ($text -replace '\s+', ' ')
    Write-Host ("  answer: " + $preview.Substring(0, [Math]::Min(420, $preview.Length)))
}

# Draft-leak guard: retrieve straight from each knowledge base with broad questions and require every reference to be
# Published, Authoritative and AI-ready. This proves the knowledge source baseFilter is enforced.
$searchEndpoint = ([uri]$state.mcpEndpoint).GetLeftPart('Authority')
$searchKey = (az search admin-key show --resource-group $state.resourceGroup --service-name $state.searchServiceName --query primaryKey -o tsv).Trim()
$searchHeaders = @{ 'api-key' = $searchKey; 'Content-Type' = 'application/json' }
$retrieveVersion = ([uri]$state.mcpEndpoint).Query -replace '.*api-version=([^&]+).*', '$1'
$leakCases = @(
    @{ Base = $state.knowledgeBaseName; Source = $state.knowledgeSourceName; Question = 'Show draft, under review, superseded or archived policies, proposals and templates' },
    @{ Base = $state.knowledgeBaseName; Source = $state.knowledgeSourceName; Question = 'What is the proposal and pricing template guidance?' }
)
Write-Host "`n[governance] Draft-leak guard" -ForegroundColor Cyan
foreach ($leak in $leakCases) {
    $body = @{
        messages = @(@{ role = 'user'; content = @(@{ type = 'text'; text = $leak.Question }) })
        knowledgeSourceParams = @(@{ knowledgeSourceName = $leak.Source; kind = 'searchIndex'; includeReferences = $true; includeReferenceSourceData = $true })
    } | ConvertTo-Json -Depth 8
    try {
        $result = Invoke-RestMethod -Method POST -Uri "$searchEndpoint/knowledgebases/$($leak.Base)/retrieve?api-version=$retrieveVersion" -Headers $searchHeaders -Body $body -TimeoutSec 180
        $bad = @($result.references | Where-Object { $_.sourceData -and ($_.sourceData.lifecycle_status -ne 'Published' -or -not $_.sourceData.authoritative -or -not $_.sourceData.ai_ready) })
        $ok = $bad.Count -eq 0
        if (-not $ok) { $failures++ }
        Write-Host ("  [{0}] {1} reference(s), {2} non-published: {3}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), @($result.references).Count, $bad.Count, $leak.Question) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
    }
    catch {
        Write-Host "  FAIL retrieve error: $($_.Exception.Message)" -ForegroundColor Red
        $failures++
    }
}

Write-Host ''
if ($failures) { Write-Host "$failures check(s) failed." -ForegroundColor Red; exit 1 }
Write-Host 'All agent checks passed.' -ForegroundColor Green



