# Azure Deployment Plan

## 1) Summary
- **Mode**: MODIFY existing deployment
- **Goal**: Deploy current code changes, then validate UI permissions/site selection and end-to-end agent behavior against SharePoint + AI Search.

## 2) Scope
- Deploy updated API/UI.
- Validate permissions retrieval in UI.
- Provision/verify multi-site SharePoint content (recordings + transcripts + office docs).
- Re-index and validate exclusion filters for draft/incomplete content.

## 3) Recipe
- **recipe.type**: azcli
- **execution path**: repository deployment scripts + Azure CLI/PowerShell.

## 4) Azure Context
- Subscription, resource group, App Service names, SharePoint host/site URLs: loaded from customer configuration and current authenticated context.

## 5) Risks / Checks
- Managed identity + Graph/SharePoint grants must exist for each selected site.
- Content indexing filters must exclude draft/incomplete documents.
- Agent citations must reference the video/transcript evidence returned by indexed content.

## 6) Execution Steps
1. Commit local changes.
2. Deploy API/UI.
3. Provision 3 functional sites and content payload.
4. Publish/index content.
5. Validate UI permissions and end-to-end agent answers/citations.

## 7) Validation Proof
- 2026-10-28T21:45Z — Azure context check:
  - `az account show --query "{tenant:tenantId,sub:id,name:name}" -o json`
  - Result: authenticated to subscription `cf824570-a8ba-497a-a184-0a52f1830aa9`, tenant `12a4b86b-e64c-43f9-af05-d9130a72dfd2`.
- 2026-10-28T21:46Z — IaC static compile:
  - `python scripts/deploy/deploy_tool.py validate-iac`
  - Result: bootstrap/app-service/foundry-agent Bicep templates compiled (`ok`).
- 2026-10-28T21:47Z — Component parameter render:
  - `python scripts/deploy/deploy_tool.py render --component ui --out .state\validate\ui`
  - `python scripts/deploy/deploy_tool.py render --component api --out .state\validate\api`
  - `python scripts/deploy/deploy_tool.py render --component foundry-agent --out .state\validate\foundry-agent`
  - Result: all parameter files rendered.
- 2026-10-28T21:47Z — ARM preflight validate:
  - `az deployment group validate --resource-group m365-myaacoub --template-file infra\bicep\components\app-service\main.bicep --parameters @.state\validate\ui\bicep-params.json`
  - `az deployment group validate --resource-group m365-myaacoub --template-file infra\bicep\components\app-service\main.bicep --parameters @.state\validate\api\bicep-params.json`
  - `az deployment group validate --resource-group m365-myaacoub --template-file infra\bicep\components\foundry-agent\main.bicep --parameters @.state\validate\foundry-agent\bicep-params.json`
  - Result: provisioningState `Succeeded` for all three validations.
- 2026-10-28T21:47Z — Policy visibility:
  - `az policy assignment list --scope /subscriptions/cf824570-a8ba-497a-a184-0a52f1830aa9 --query "[?enforcementMode=='Default'].{name:name,scope:scope}" -o table`
  - Result: enforced assignments listed; no blocking deny surfaced in this validation pass.
- 2026-10-28T21:48Z — Build verification:
  - `python -m pytest app\api\tests -q` → `107 passed`
  - `npm --prefix app\ui run build` → success
- 2026-10-28T21:49Z — Static RBAC review:
  - `rg "roleAssignments|roleDefinitionId|Foundry User|Contributor|User Access Administrator|AcrPull" infra\bicep -n`
  - Result: expected role assignment resources present in bootstrap and foundry-agent templates.

## 8) All validation checks pass
- [x] 1. Core Validation (CLI, auth, build, validate, what-if)
- [x] 2. Docker Build (if containerized)
- [x] 3. Azure Policy Validation

## Status
Validated
