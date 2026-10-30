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
    @{ Hub = 'hr'; Site = 'hrknowledgehub'; Question = 'In the open enrollment planning review meeting, what did the team say about the HSA employer contribution?' },
    @{ Hub = 'manufacturing'; Site = 'manufacturingknowledgehub'; Question = 'What is the target torque for the Station 7 torque sequence and why was the sequence changed?' },
    @{ Hub = 'manufacturing'; Site = 'manufacturingknowledgehub'; Question = 'What did the Line 3 yield improvement tollgate meeting say about seal leak defects?' },
    @{ Hub = 'sales'; Site = 'salesmarketingknowledgehub'; Question = 'What discount level requires deal desk approval before a proposal is sent?' },
    @{ Hub = 'sales'; Site = 'salesmarketingknowledgehub'; Question = 'What did the win-loss debrief meeting conclude about why we win and lose deals?' }
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
    $citedSite = $text -match [regex]::Escape("/sites/$($case.Site)/")
    $checks = [ordered]@{ 'returned text' = -not [string]::IsNullOrWhiteSpace($text); 'called knowledge base' = $calledKnowledge; "cited $($case.Site)" = $citedSite }
    foreach ($check in $checks.GetEnumerator()) {
        $label = if ($check.Value) { 'PASS' } else { 'FAIL'; $failures++ }
        Write-Host ("  [{0}] {1}" -f $label, $check.Key) -ForegroundColor $(if ($check.Value) { 'Green' } else { 'Red' })
    }
    $preview = ($text -replace '\s+', ' ')
    Write-Host ("  answer: " + $preview.Substring(0, [Math]::Min(420, $preview.Length)))
}

Write-Host ''
if ($failures) { Write-Host "$failures check(s) failed." -ForegroundColor Red; exit 1 }
Write-Host 'All agent checks passed.' -ForegroundColor Green
