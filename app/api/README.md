# SharePoint governance API

## What this service is

A FastAPI service in `app\api`. It reads SharePoint and Microsoft Graph with its managed identity and returns libraries, folders, item permissions, access by user, exposure findings, analytics (duplicates, expiry, anomalies), hygiene metrics, owner notification drafts (dry run by default), and the Foundry agent endpoint. Data routes require an Entra token with the Auditor role.

## Layout

```text
app\api\
  app\
    asgi.py              ASGI entry point (app.asgi:app)
    factory.py           builds the app and mounts the routers
    core\config.py       loads config\, shared files and environment overrides
    auth\validator.py    Entra bearer token checks and the Auditor role
    api\routes\          route modules: access, agent, analytics, documents,
                         hygiene, notifications, sites, system
    services\            business logic (for example notifications.py)
  config\                JSON settings (see Configuration)
  tests\                 pytest suite; conftest.py and helpers\ hold fixtures
  requirements.txt       runtime packages
  requirements-dev.txt   adds pytest
..\..\config\            shared governance files named in sharedConfig
..\..\deploy\            App Service settings and component definitions
..\..\.github\workflows\ pipelines, including api.yml
```

## Run locally

Run these commands from `app\api`. Use Python 3.12, the App Service runtime (see `..\..\deploy\README.md`).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
$env:API_CONFIG__auth__audience = "api://<API_APP_CLIENT_ID>"
$env:API_CONFIG__auth__clientId = "<API_APP_CLIENT_ID>"
python -m uvicorn app.asgi:app --port 8000
```

- Replace `<API_APP_CLIENT_ID>` with the client ID of the API app registration. While a placeholder remains, startup stops with a `ConfigError`.
- App Service runs gunicorn with the Uvicorn worker. gunicorn does not run on Windows, so use uvicorn locally.
- `API_CONFIG_PATH` (no prefix) selects another API config file, relative to `app\api`. The default is `config/api.config.json`.
- Run the tests with `python -m pytest -q`.

## Configuration

| File | Controls |
|---|---|
| `api.config.json` | Server host and port; `routePrefix` (`/api/v1`); docs, ReDoc and OpenAPI paths; CORS; `auth` (audience, clientId, `requiredRole`, issuer template, signing-key cache, clock skew); `identity` (managed identity client ID, Graph and SharePoint token scopes); `graph` (page size, timeouts, retries, concurrency); `sharePoint` (paging, crawl limits, principal and link mapping); `api` (page sizes, sortable fields); `hygiene`; `cache` (TTLs); `sharedConfig` (paths to the shared deployment, vocabulary and policy files). The SharePoint site URL comes from the shared deployment file. |
| `agent.json` | `foundry` (project endpoint template, account, project and agent names, token scope, timeouts, retries). The three names are null by default; until they are set, the agent answers from live evidence only. Also answer limits, `fallbackIntent` (`help`), `draftNotification`, `findingIds`, answer and message text, `instructions` (not reproduced here) and the `intents` list: overexposure, access-review, broken-inheritance, duplicates, expired-content, ownership-gaps, stale-content, owner-notification, backlog-summary, orphaned-access, conflicts, help. |
| `agent-prompts.json` | Provisional sample prompts grouped by issue (intent id). Each intent must exist in `agent.json`. Returned by `GET /api/v1/agent/prompts`. |
| `analytics.json` | TF-IDF settings; duplicate clustering (`duplicates`); anomaly model (`anomaly`: contamination, estimators, seed, top N, features); expiry date patterns and review grace days (`expiry`); exposure rules and labels (`exposure`); text extraction limits (`extraction`); login-name patterns. Exposure severities: critical for anonymous links and Everyone including external users; high for Everyone except external users and orphaned accounts; medium for organization links, external direct grants and broken inheritance; low for specific-people links. |
| `notifications.json` | `mode` (`dryRun` by default); `outboxPath`; `sender.userPrincipalName` (holds the placeholder `<SENDER_UPN>`); `maxPerBatch` (25); `dedupeWindowHours` (72); `messages` (fallback, refusal and delivery text); `templates` (subject and body per finding id: expired-documents, requires-review, draft-documents, superseded-documents, exact-duplicates, near-duplicates, conflicting-authoritative, conflicts-with-authoritative). |

## Environment overrides

- `API_CONFIG__<SECTION>__<KEY>` overrides a value in `api.config.json`, for example `API_CONFIG__cors__allowedOrigins`. Nested keys add segments, for example `API_CONFIG__graph__pageSize`.
- `API_AGENT__<SECTION>__<KEY>` overrides `agent.json`, for example `API_AGENT__foundry__accountName`. There is no override prefix for `analytics.json` or `notifications.json`; edit those files.
- Key names match case-insensitively. A name that matches no key stops startup.
- Values take the type of the value they replace: booleans accept true/false, 1/0, yes/no or on/off; numbers must parse; objects must be JSON; other values are text.
- List values are comma-separated text (`a,b,c`). Use a JSON array (`["a,b","c"]`) when an item contains a comma.
- Overrides apply before validation. A `<...>` placeholder left in `api.config.json` or `agent.json` stops startup with one `ConfigError` that lists every problem, for example `api.config.json: auth.clientId still contains the placeholder <API_APP_CLIENT_ID>. Replace it in the file or export API_CONFIG__auth__clientId.` Empty required values fail the same way; `auth.audience` and `auth.clientId` are required.

## Authentication

- Bearer tokens must be Entra ID v2 access tokens signed with RS256. Signing keys come from the tenant JWKS (`auth.authorityHostUrl` and `auth.jwksPath`).
- The issuer must be `https://login.microsoftonline.com/{tenantId}/v2.0` for the configured tenant.
- `aud` must be the API client ID or `api://<client ID>`. Both forms are accepted; any other audience fails with `invalid_audience`.
- The token must carry the app role named in `auth.requiredRole`, which is `Auditor` in the default config. Without it the API returns 403. Missing, expired or invalid tokens return 401.
- Required claims are exp, iat, aud and iss. The clock skew allowance is 300 seconds.
- Open without a token: the root `GET /health` (App Service liveness probe), `GET /api/v1/health` and `GET /api/v1/policy`. Every other route under `/api/v1` requires a token.

## Endpoints

Paths are relative to `/api/v1`. Every row needs a token with the Auditor role except the two rows marked open. The root `GET /health` is also open.

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness and configuration status (no token). |
| `GET /policy` | Governance labels, hygiene definitions and policy thresholds (no token). |
| `GET /me` | The signed-in auditor and the roles on the token. |
| `GET /site` | Site name, URL and configured library count. |
| `GET /site/libraries` | Configured document libraries of the site. |
| `GET /site/libraries/{libraryId}/children` | Folders and files of one folder level (lazy tree). |
| `GET /items/{itemId}/permissions` | Permission entries for a library, folder or file. |
| `GET /access/users` | Search site users by name, UPN, email or login. |
| `GET /access/users/{userKey}/items` | Every item a user can reach, with role and grant path. |
| `GET /documents` | Governance list of documents, filtered by lifecycle, data quality, authoritative flag and knowledge category (`knowledgeCategory`), and paged. Returns `knowledgeCategories`, the categories in the library, for the category filter. |
| `GET /documents/{itemId}` | One document with trust reasons, conflicts and duplicate status. |
| `GET /analytics/duplicates` | Exact and near-duplicate clusters with canonical copies. |
| `GET /analytics/expiry` | Expired and review-overdue documents from metadata and text dates. |
| `GET /analytics/anomalies` | IsolationForest anomaly scores with per-feature contributions. |
| `GET /analytics/exposure` | Over-exposure findings from grants, links, guests and orphaned accounts. |
| `GET /hygiene` | Governance hygiene metrics, findings and coverage. |
| `GET /hygiene/findings/{findingId}` | All documents behind one hygiene finding. |
| `POST /notifications/drafts` | Create owner notification drafts from a template. |
| `GET /notifications` | List notifications, optionally by status. |
| `POST /notifications/{notificationId}/approve` | Approve a draft so it can be sent. |
| `POST /notifications/{notificationId}/send` | Send an approved notification (dryRun records only). |
| `GET /agent/prompts` | Provisional sample prompts for the cleanup issues. |
| `POST /agent/messages` | Ask a governance question; answered from live evidence. |

## Notifications

- Flow: create drafts with `POST /notifications/drafts`, approve each draft, then send it. Only approved drafts can be sent.
- `mode` is `dryRun` by default. In dryRun nothing is delivered: a send is refused with the text in `messages.sendRefused`, and the draft stays in the outbox.
- Delivery needs a mode other than dryRun and uses Microsoft Graph sendMail (`messages.sendDelivery`). `sendAsReviewer` is one such mode; it requires `sender.userPrincipalName`, which is still the placeholder `<SENDER_UPN>` in the repo.
- The outbox is a JSON file at `outboxPath`. The default value is `.state/notifications/outbox.json`, resolved relative to `app\api`.

## Deploy

- The API component is defined in `..\..\deploy\components\api.json`. Its startup command is `gunicorn -k uvicorn.workers.UvicornWorker app.asgi:app --bind 0.0.0.0:8000 --timeout 120`.
- See `..\..\deploy\README.md` for the workflows and Bicep.
- The API deploys to App Service only through the `api` workflow (`..\..\.github\workflows\api.yml`), on pushes to `main`. Pull requests run only its validate job. The deploy job also requires the `AZURE_CLIENT_ID` variable to be set.

## Tests

- Install `requirements-dev.txt`, then run `python -m pytest -q` from `app\api`.
- Test modules in `tests\`: test_agent.py, test_analytics.py, test_api_surface.py, test_auth.py, test_config.py, test_grant_paths.py, test_hygiene_documents.py, test_libraries.py, test_notifications.py and test_permissions.py.
- Fixtures are in `tests\conftest.py` and `tests\helpers\` (fake_tenant.py, office.py, settings.py). Tenant-style domains in the fixtures are synthetic: contoso.com and contoso.sharepoint.com.
