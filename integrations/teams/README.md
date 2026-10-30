# Save as Knowledge: Teams chat workflow (Power Automate)

A message action in Teams that promotes **one deliberately selected message** into governed SharePoint knowledge.

```text
Teams chat message
  → ⋯ More actions → "Save as Knowledge"      (For a selected message trigger)
  → API drafts structured knowledge with AI   (POST /knowledge/teams/draft)
  → Adaptive Card in Teams: review and edit   (nothing is saved yet)
  → Publish to SharePoint                     (POST /knowledge/teams/publish)
  → Card: "Knowledge preserved" + Open in SharePoint + Ask AI about this
  → Indexing... → Available to AI             (existing Azure AI Search / Foundry IQ pipeline)
```

It is a *promote* workflow, not an archive: only the selected message is sent, the user must approve, only the
summarized knowledge is stored, and the conversation is not kept. See the *Save to Knowledge Demo* section of the
[main README](../../README.md#save-to-knowledge-demo) for the whole feature.

## What is in this folder

| File | Purpose |
| --- | --- |
| `save-to-knowledge.connector.swagger.json` | OpenAPI 2.0 definition for a Power Platform **custom connector** (4 actions). |
| `samples/teams-draft.request.json` | The body the flow sends to `/knowledge/teams/draft`. |
| `samples/review-card.json` | The review Adaptive Card the API returns (paste it into the [Adaptive Cards designer](https://adaptivecards.io/designer/) to preview). |
| `samples/card-submission.json` | What Teams returns in `data` when the user selects **Publish to SharePoint**. |
| `samples/success-card.json` | The "Knowledge preserved" card. |

The samples are real API output for the sample message "We confirmed the qualification issue was caused by firmware
4.8.2...". Regenerate them from the API whenever the card layout changes.

> The flow is built in Power Automate and cannot be imported from this repository. Importable flow packages depend on
> connector operation IDs and connection references from your tenant, so the steps below are the supported route.
> The API contract and the cards are tested; the flow itself is configuration.

## Prerequisites

1. The API is deployed and reachable over HTTPS from Power Platform (the App Service from [deploy/README.md](../../deploy/README.md)).
2. Save to Knowledge is configured for live use (README, *Save to Knowledge Demo*): `publish.mode = graph`,
   `indexing.mode = search`, and the extraction model deployment set. With the defaults the flow still runs, but
   publishes to the API's local demo folder and uses the demo extractor.
3. Teams admin center: the **Power Automate Actions** app (App ID `00001016-de05-492e-9106-4828fc8a8687`) is
   allowed. The flow must be created in the **default** Power Platform environment to appear as a Teams message action.
   (Microsoft Learn: [Trigger a cloud flow from any message in Teams](https://learn.microsoft.com/power-automate/trigger-flow-teams-message).)
4. A Power Automate plan that allows **custom connectors** (a premium capability).
5. Optional but recommended for the success card: set `API_KNOWLEDGE__teams__webAppUrl` to the governance web
   app's URL so the card shows **Ask AI about this**.

## 1. Authentication: delegated, so the user is the owner

The custom connector signs in **as the Teams user** (OAuth 2.0, Microsoft Entra ID). The API validates that token
exactly as it does for the web app, so the same `Auditor` role gates access, and the signed-in user becomes the default
knowledge owner. No shared secret identifies the user.

1. In the Entra ID **API app registration** (the one that exposes `access_as_user`, see the
   [customer setup guide](../../docs/CUSTOMER-SETUP-GUIDE.md)), nothing changes.
2. Create a **new app registration** for the connector, for example *Save to Knowledge connector*:
   - Redirect URI (Web): `https://global.consent.azure-apim.net/redirect`
   - Certificates & secrets: create a client secret (store it in the connector, not in source control).
   - API permissions → delegated → `api://<API_CLIENT_ID>/access_as_user`; grant consent.
3. In the API registration → *Expose an API* → *Authorized client applications*, add the connector's client ID with
   the `access_as_user` scope (optional pre-authorization).
4. Users who will use the action need the **Auditor** app role on the API's enterprise application. Without it the
   API answers 403 and the flow's error handler tells the user so.

## 2. Create the custom connector

Power Automate → **Data → Custom connectors → New custom connector → Import an OpenAPI file** and select
`save-to-knowledge.connector.swagger.json`.

- **General:** Host = your API host (for example `<API_APP_NAME>.azurewebsites.net`), base URL `/api/v1`.
- **Security:** OAuth 2.0 → Identity provider **Azure Active Directory**; Client id / secret from step 1.2;
  Tenant ID = your tenant (do not leave `common`); Resource URL = `api://<API_CLIENT_ID>`;
  Scope = `api://<API_CLIENT_ID>/access_as_user`. Save, then copy the generated redirect URL back into the connector
  app registration if it differs.
- **Definition:** the four operations are already defined. **Create connector**, then **Test** `DraftFromTeamsMessage`
  with `samples/teams-draft.request.json`.

## 3. Build the flow

Create the flow at [make.powerautomate.com](https://make.powerautomate.com) (default environment), for example
from the Teams **Workflows** app → **Build your own**. Name it **Save as Knowledge**.

| # | Step | Configuration |
| --- | --- | --- |
| 1 | Trigger: **Microsoft Teams → For a selected message** | Message action name: `Save as Knowledge`. Leave the optional input card empty. |
| 2 | **Scope: Try** | Put steps 3-8 inside it. |
| 3 | **Save to Knowledge → Draft from Teams message** | `messageText` = **Plain text message output**; `senderName` = **Sender display name**; `messageLink` = **Link to message**; `messageId` = **Message ID**; `postedAt` = **Message creation time** (if offered). |
| 4 | **Microsoft Teams → Post adaptive card and wait for a response** | Post as **Flow bot**, in **Chat with Flow bot**, Recipient = **Originating user email**. Message = `string(body('Draft_from_Teams_message')?['card'])`. Update message = *Thanks, working on it...*; Should update card = **Yes**. |
| 5 | **Condition** | `body('Post_adaptive_card_and_wait_for_a_response')?['data']?['action']` **is equal to** `publish`. |
| 6 | **Yes:** **Save to Knowledge → Publish from Teams card** | Body = `body('Post_adaptive_card_and_wait_for_a_response')?['data']` (the card's submitted values, including `action`). |
| 7 | **Yes:** **Microsoft Teams → Post adaptive card in a chat or channel** | Flow bot → Chat with Flow bot → Originating user. Message = `string(body('Publish_from_Teams_card')?['card'])`. |
| 8 | **Yes (optional):** **Do until** `body('Get_indexing_status')?['stage']` is `available`, `failed`, `notReady` or `delayed` | Inside: **Delay** 2 minutes, then **Get indexing status** with `artifactId` = `body('Publish_from_Teams_card')?['result']?['artifactId']`, `publishedAt` = `body('Publish_from_Teams_card')?['result']?['publishedAt']`, `aiReady` = `body('Publish_from_Teams_card')?['result']?['aiReady']`. Limit: count 10. After the loop, **Post message in a chat or channel** with `body('Get_indexing_status')?['message']`. To skip waiting for the schedule, call **Refresh the index now** once before the loop. |
| 9 | **No:** nothing | The user cancelled. Nothing was saved. |
| 10 | **Scope: Catch**, *Configure run after* = **has failed**, **has timed out** | **Filter array** on `result('Try')` where `item()?['status']` equals `Failed`; then **Post message in a chat or channel** to the originating user: `Save to Knowledge could not complete: ` + `first(body('Filter_array'))?['error']?['message']`. |

Notes:

- The connector returns the API's error envelope on failure, so the catch step shows a specific message, for example
  *"SharePoint: write access was denied ... Sites.Selected 'write' role ..."*, *"the model did not return knowledge in
  the required structure"*, or *"Review date must be in the future."*.
- Teams' **For a selected message** trigger sends one message. To capture a thread, select the most useful message
  (usually the one that states the decision or fix); the card lets the user add anything missing before publishing.
- Flow action names in the expressions above are the defaults Power Automate generates; adjust them if you rename steps.

## 4. What the user sees

1. In a chat: message **⋯ → More actions → Save as Knowledge**.
2. Within seconds, a Flow bot card **Promote to Knowledge**:
   - *AI detected*: Type, Title, Department, Source = Teams collaboration, Status = Draft.
   - Editable fields (title, summary, category, context, root cause, decision, recommended action, key facts,
     department, product, owner, sensitivity, review date, tags). Each label says whether the value is *from the
     message*, *AI suggested*, a *default* or *not stated*.
   - **Publish to SharePoint** (requires the confirmation toggle) or **Cancel**.
3. After publishing: **Knowledge preserved** with title, SharePoint location, category, owner, published date, review
   date and lifecycle status, plus **Open in SharePoint** and **Ask AI about this**.
4. A follow-up message: *Published to SharePoint → Indexing... → Available to AI*.

## Test the API without Teams

```powershell
$token = az account get-access-token --resource "api://<API_CLIENT_ID>" --query accessToken -o tsv   # signed-in Auditor
$h = @{ Authorization = "Bearer $token" }
$draft = Invoke-RestMethod -Method Post -Uri "https://<API_HOST>/api/v1/knowledge/teams/draft" -Headers $h `
    -ContentType 'application/json' -InFile .\samples\teams-draft.request.json
$draft.card | ConvertTo-Json -Depth 20          # paste into https://adaptivecards.io/designer/
Invoke-RestMethod -Method Post -Uri "https://<API_HOST>/api/v1/knowledge/teams/publish" -Headers $h `
    -ContentType 'application/json' -InFile .\samples\card-submission.json
```

(`az account get-access-token` works when your Azure CLI client is pre-authorized for the API; otherwise use the web app.)

## Governance notes

- **No automatic capture.** The flow runs only when a user selects the message action.
- **Human in the loop.** `Authoritative` and publication need the explicit confirmation toggle; AI never sets them.
- **No bypass of retention.** Only the reviewed summary and its provenance are stored; the message text is not kept
  in SharePoint, and the API does not persist it (the Foundry call uses `store: false`).
- **SharePoint permissions apply.** The document lands in the configured library and inherits its permissions.
