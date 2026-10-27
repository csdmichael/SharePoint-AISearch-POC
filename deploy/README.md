# Deployment

This folder holds the deployment contract for the SharePoint governance POC. The contract is `deploy/settings.json` plus one descriptor per component. The workflows and the helper script read these files.

## 1. Purpose

Each component deploys on its own. A component's workflow runs only when a file that matches its `triggerPaths` changes. The workflow files repeat those paths as literal `paths` filters.

- A push to `main` validates and, for deployable components, deploys.
- A pull request only validates. It never deploys.
- The deploy job also needs the repository variable `AZURE_CLIENT_ID`. Until that variable is set, pushes validate and skip the deploy.

The deployable components (`ui`, `api`, `foundry-agent`) also list `deploy/settings.json`, `infra/**`, `scripts/deploy/**`, `scripts/ci/**` and `.github/workflows/**`. A change to any of those paths redeploys all three.

## 2. Layout

- `deploy/settings.json`: tenant, subscription, resource group, location, App Service plan, GitHub settings, bootstrap and Terraform state settings, packaging excludes, and health check retries.
- `deploy/components/<id>.json`: one descriptor per component. It sets the source path, trigger paths, validation commands, package steps, Bicep template, App Service name, runtime and app settings.
- `scripts/deploy/deploy_tool.py`: standard-library helper used by the workflows and by hand. Its subcommands are listed in section 9.
- `.github/workflows/`: `ui.yml`, `api.yml`, `foundry-agent.yml` and `trusted-knowledge.yml` call the reusable `_component.yml`, which runs the validate and deploy pipeline. `infra.yml` runs `validate-iac` directly.
- `infra/bicep/bootstrap/main.bicep`: one-time admin bootstrap (section 5).
- `infra/bicep/components/app-service/main.bicep`: App Service template used by `ui` and `api`.
- `infra/bicep/components/foundry-agent/main.bicep`: Foundry project and role grants used by `foundry-agent`.
- `infra/terraform/`: does not exist. Terraform is planned, not wired yet. The descriptors name Terraform roots and list `terraform` in `supportedTools`, but the helper accepts only `--tool bicep`.

## 3. Components

| id | What it deploys | Workflow | Main trigger paths |
| --- | --- | --- | --- |
| `ui` | App Service `caldova-aiscr-ui` on Node 22. Serves the built Ionic/Angular UI with `node server/static-server.mjs`. | `ui.yml` | `app/ui/**` |
| `api` | App Service `caldova-aiscr-api` on Python 3.12. FastAPI under gunicorn with the Uvicorn worker. Health path `/health`. | `api.yml` | `app/api/**`, `config/trusted-knowledge.json`, `config/governance-*.json` |
| `foundry-agent` | Foundry project `SharePointGovernance`, the Foundry User role for `caldova-aiscr-api`, and agent `sharepoint-governance-agent`, created or versioned by upsert. | `foundry-agent.yml` | `app/api/config/**`, `app/api/app/agent/**` |
| `trusted-knowledge` | Nothing is deployed. Validation only: Python 3.13 unit tests. | `trusted-knowledge.yml` | `scripts/trusted_knowledge/**`, `tests/**`, `config/trusted-knowledge.json`, `config/governance-*.json` |
| `infra` | Nothing is deployed. Bicep validation with `validate-iac`. | `infra.yml` | `infra/**`, `deploy/settings.json`, `scripts/deploy/**` |

Each component's trigger list includes its own descriptor. The `infra` workflow has no descriptor and no deploy job.

## 4. What a deploy does

A caller workflow runs `validate` when one of its trigger paths changes. This happens on pushes to `main` and on pull requests. The `deploy` job waits for `validate`. It runs only on a push to `main`, uses the GitHub environment `production`, and does not cancel a running deploy for the same component.

Validate runs the `install`, `unitTest`, `build` and `e2e` phases that the descriptor defines. Only `ui` defines `e2e` (Playwright).

Deploy, in order:

1. Read component and settings fields with `info` and `setting`.
2. Node components: install and build in CI. Python components: set up Python from `language.version`.
3. `appService` only: `package` stages the source and writes `<id>.zip`. For `ui`, it also patches `www/assets/config/app.config.json` with the API URL and sign-in values. For `api`, `package.vendorPython` installs the Linux wheels (cp312, manylinux) of `requirements.txt` into `.python_packages`, so App Service runs no build.
4. `appService` only: `smoke` starts the packaged app with `azure.startupCommand` and `azure.appSettings` (the App Service folder is replaced by the extracted zip) and checks `azure.healthPath`. A failure stops the deploy before Bicep, so the running app keeps its current settings.
5. Sign in to Azure with OpenID Connect (`azure/login@v2`, `id-token: write`). No client secret is used.
6. Render `bicep-params.json` with `render` (`appService` and `foundryAgent` kinds). Bicep sets `appCommandLine` and the complete `appSettings` collection.
7. Run `az deployment group create` with the component's Bicep template.
8. `appService` only: `az webapp deploy --type zip --clean true --restart true --async true`.
9. `appService` only: `Wait for App Service deployment` polls the Kudu deployment list until the latest deployment completes with status 4 (up to 45 checks, 20 seconds apart). It fails on any other final status. A restart while Kudu is still unpacking the app stops the deployment, so the restart waits for this step.
10. `appService` only: `az webapp restart`.
11. `appService` only: `health` polls `https://<appName>.azurewebsites.net<healthPath>` up to `healthCheck.attempts` times, `healthCheck.delaySeconds` apart (`deploy/settings.json`). Any HTTP status from 200 to 399 passes.
12. `foundryAgent` only: `upsert-foundry`.

`upsert-foundry` reads the agent from the Foundry project. It creates the agent when it is missing. If the latest version already has the same instructions and model, it reports "up to date" and posts nothing. Otherwise it posts a new agent version. Instructions come from the `instructions` property of `app/api/config/agent.json`. The model is `foundry.modelDeployment`.

## 5. One-time bootstrap (already run for this repository)

An admin runs this once from a checkout. CI never deploys the bootstrap template. The admin needs rights to create role assignments on the resource group and the Foundry account.

1. Render the parameters: `python scripts/deploy/deploy_tool.py render-bootstrap --out <dir>`
2. Deploy to the resource group named in `deploy/settings.json`:
   `az deployment group create --resource-group <resourceGroup> --template-file infra/bicep/bootstrap/main.bicep --parameters @<dir>/bicep-params.json`
3. The deployment creates:
   - the user-assigned identity `id-spacl-github-deploy`, with a federated credential whose subject is `deployIdentity.subject` in settings (`repo:<owner>/<repository>:environment:production`) and audience `api://AzureADTokenExchange`
   - Contributor on the resource group
   - User Access Administrator on the Foundry account
   - the Terraform state storage account and its `tfstate` container, with Storage Blob Data Contributor on that account for the identity
4. In GitHub, set the repository variables `AZURE_CLIENT_ID` (the deployment output `clientId`), `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`. Create the environment `production`.

Never store a client secret. The identity signs in with OpenID Connect.

## 6. Adding a component

1. Create `deploy/components/<id>.json` with `"schemaVersion": "deploy-component/v1"`. Copy a descriptor of the same kind. Set `kind` to `appService` or `foundryAgent`, the only kinds the helper deploys.
2. Set `infra.bicepTemplate` to the component's template and make sure the file exists. `validate-iac` builds every template that a descriptor of these kinds names.
3. Add `.github/workflows/<id>.yml`. Copy the `paths` list from `triggerPaths`. Copy the two jobs that call `_component.yml` from `ui.yml`: `validate` with `mode: validate`, and `deploy` with `needs: validate`, the same `if` condition and `mode: deploy`. Both pass `component: <id>`.
4. Run the checks in section 9.

## 7. Important behaviour

- App settings are replaced on every App Service deploy. The Bicep template PUTs the whole `appsettings` collection, so any setting missing from the descriptor's `azure.appSettings` is removed. List every setting the app needs. Values must be strings.
- `ui` and `api` set `SCM_DO_BUILD_DURING_DEPLOYMENT` to `false`. CI builds the UI. The API's dependencies are vendored at package time (`package.vendorPython`), and `PYTHONPATH` points at `.python_packages/lib/site-packages`. The earlier setting made App Service run an Oryx build on the server, which took 15 to 40 minutes.
- `render` writes the parameter file to `--out`. In CI that folder is under `$RUNNER_TEMP`, so the checkout stays clean.

## 8. Limits

- GitHub path filters must be literal YAML, so each workflow copies its component's `triggerPaths`. When you change a descriptor's `triggerPaths`, update the workflow's `paths` to match. No check compares them today.
- Terraform is planned, not wired. There is no `infra/terraform` folder, and only `--tool bicep` works.
- Trusted Knowledge live provisioning (SharePoint library, Search index, Foundry knowledge base) is not part of CI. The `trusted-knowledge` component runs validation only.
- Bicep 0.47 warns (BCP081) about the `2026-09-01` Foundry types. The templates still compile.

## 9. Local checks

Run these from the repository root. None of them deploys anything.

- `python scripts/deploy/deploy_tool.py validate-iac`: runs `az bicep build` on the bootstrap template and on each deployable component template. Needs the Azure CLI with Bicep.
- `python scripts/deploy/deploy_tool.py info --component ui --field azure.appName`: prints one descriptor field. `setting --field location` prints one settings field.
- `python scripts/deploy/deploy_tool.py run --component api --phase unitTest`: runs one validation phase in the component's `sourcePath`.
- `python scripts/deploy/deploy_tool.py package --component ui --out <dir>`: stages the app and writes `<dir>/ui.zip`.
- `python scripts/deploy/deploy_tool.py upsert-foundry --component foundry-agent --dry-run`: read only. It reports what the upsert would do. It needs an Azure CLI sign-in because it reads the Foundry project.
