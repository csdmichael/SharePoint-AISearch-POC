# SharePoint Semiconductor Knowledge Search

This proof of concept turns source-grounded semiconductor data from Azure
Databricks into a rich Microsoft 365 document corpus and indexes it directly
from SharePoint Online with [Azure AI Search](https://learn.microsoft.com/azure/search/search-what-is-azure-search).
[Foundry IQ](https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-foundry-iq)
exposes the promoted chunk index through a knowledge source and knowledge base,
and a Microsoft Foundry prompt agent returns grounded answers with citations.

The solution does **not** copy or stage SharePoint files in Azure Blob Storage.
SharePoint Online remains the document system of record.

## Table of contents

1. [Solution status](#solution-status)
2. [Deployed URLs](#deployed-urls)
3. [Architecture](#architecture)
4. [Data and corpus](#data-and-corpus)
5. [Repository layout](#repository-layout)
6. [Configuration](#configuration)
7. [Prerequisites](#prerequisites)
8. [Deploy the solution](#deploy-the-solution)
9. [Azure AI Search design](#azure-ai-search-design)
10. [Security model](#security-model)
11. [Operations and validation](#operations-and-validation)
12. [Relevance evaluation and feedback](#relevance-evaluation-and-feedback)
13. [Foundry agent integration](#foundry-agent-integration)
14. [Sample prompts](#sample-prompts)
15. [Preview limitations](#preview-limitations)
16. [Cost and production scaling](#cost-and-production-scaling)
17. [Additional references](#additional-references)
18. [License](#license)

## Solution status

| Component | Configuration | Status |
| --- | --- | --- |
| Databricks source | Six tables in `{Databricks Catalog}.{Databricks Schema}` | Profiled through `{Profile Source Agent}` |
| Office corpus | `{DOCX Count}` DOCX, `{PPTX Count}` PPTX, `{XLSX Count}` XLSX | `{Expected Document Count}` structurally validated |
| Azure AI Search | `{Search SKU}`, `{Azure Region}`, `{Partition Count}` partition, `{Replica Count}` replica | Deployed |
| Embeddings | `{Embedding Deployment}`, `{Embedding Dimensions}` dimensions | Deployment authorized for Search |
| SharePoint site and library | Private Microsoft 365 group site, `{Expected Document Count}` files | Deployed and validated |
| Direct SharePoint indexer | `{Search Service API Version}`, `{Indexer Schedule}` | `{Expected Document Count}` files processed, zero failed, `{Indexed Chunk Count}` chunks indexed |
| Foundry IQ | `{Knowledge Source}` -> `{Knowledge Base}` -> `{Foundry Agent}` | Agent active and citation smoke test passed |
| Ranking evaluation | `{Evaluation Case Count}` hybrid semantic/vector queries | Routing thresholds passed |
| Feedback loop | `{Feedback Index}` | Deployed and write-tested |

SharePoint Online is a Microsoft 365 service, so the site itself is not an
Azure resource inside `{Resource Group}`. Azure AI Search, Databricks, Foundry,
and related Azure resources are in the configured resource group.

## Deployed URLs

| Resource | URL |
| --- | --- |
| SharePoint site | [Semiconductor Knowledge Hub](https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub) |
| SharePoint library | [Semiconductor Knowledge](https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub/Semiconductor%20Knowledge/Forms/AllItems.aspx) |
| Azure AI Search portal | [semiconductor-search-myaacoub](https://portal.azure.com/#@caldova37587778.onmicrosoft.com/resource/subscriptions/cf824570-a8ba-497a-a184-0a52f1830aa9/resourceGroups/m365-myaacoub/providers/Microsoft.Search/searchServices/semiconductor-search-myaacoub/overview) |
| Search endpoint | [semiconductor-search-myaacoub.search.windows.net](https://semiconductor-search-myaacoub.search.windows.net) |
| Search Explorer | [Open Search Explorer](https://portal.azure.com/#@caldova37587778.onmicrosoft.com/resource/subscriptions/cf824570-a8ba-497a-a184-0a52f1830aa9/resourceGroups/m365-myaacoub/providers/Microsoft.Search/searchServices/semiconductor-search-myaacoub/searchExplorer) |
| Databricks workspace | [caldova-dbx-westus2](https://portal.azure.com/#@caldova37587778.onmicrosoft.com/resource/subscriptions/cf824570-a8ba-497a-a184-0a52f1830aa9/resourceGroups/m365-myaacoub/providers/Microsoft.Databricks/workspaces/caldova-dbx-westus2/overview) |
| Foundry resource | [foundry-myaacoub-private](https://portal.azure.com/#@caldova37587778.onmicrosoft.com/resource/subscriptions/cf824570-a8ba-497a-a184-0a52f1830aa9/resourceGroups/m365-myaacoub/providers/Microsoft.CognitiveServices/accounts/foundry-myaacoub-private/overview) |
| Foundry IQ agent | [Open the deployed SharePoint agent](https://ai.azure.com/nextgen/r/z4JFcKi6SXqhhApS8YMKqQ,m365-myaacoub,,foundry-myaacoub,proj-default/build/agents/sharepoint-agent/build?tid=12a4b86b-e64c-43f9-af05-d9130a72dfd2) |

The deployment scripts write confirmed, non-secret resource identifiers and
URLs under `.state/`. That folder is intentionally ignored by Git.
Applications should query `{Search Index Alias}`, not a timestamped physical
index name. All non-URL placeholders in this document map to
`config/deployment.json` or generated `.state` evidence.

## Architecture

```mermaid
flowchart LR
    DBX[Azure Databricks<br/>{Databricks Schema} tables]
    MCP[Private Databricks MCP]
    PROFILE[Profile-source Foundry agent]
    GEN[Corpus generator]
    SP[SharePoint Online<br/>{Production Library}]
    IDX[SharePoint indexer<br/>{Search Service API Version}]
    SPLIT[Text Split skill<br/>{Chunk Size} + {Chunk Overlap}]
    EMB[Embedding model<br/>{Embedding Dimensions} dimensions]
    SEARCH[Promoted chunk index<br/>semantic + vector + keyword]
    KS[Foundry IQ<br/>knowledge source]
    KB[Foundry IQ<br/>knowledge base]
    AGENT[Foundry prompt agent]

    DBX --> MCP --> PROFILE --> GEN --> SP
    SP --> IDX --> SPLIT --> EMB --> SEARCH
    SEARCH --> KS --> KB --> AGENT
```

There is no Blob Storage hop between SharePoint and Azure AI Search. The
indexer's data source has type `sharepoint` and its `includeLibrary` query is
scoped to the dedicated document library.

## Data and corpus

The source profile contains six fully qualified Databricks tables:

- `{Databricks Catalog}.{Databricks Schema}.defect_analysis`
- `{Databricks Catalog}.{Databricks Schema}.fab_production`
- `{Databricks Catalog}.{Databricks Schema}.inventory`
- `{Databricks Catalog}.{Databricks Schema}.product_sales`
- `{Databricks Catalog}.{Databricks Schema}.supply_chain`
- `{Databricks Catalog}.{Databricks Schema}.wafer_yield`

The profile is obtained through `{Profile Source Agent}` and its private
Databricks MCP connection. It includes aggregate metrics,
schema definitions, source SQL, quality notes, and a bounded representative
sample. No direct personal-identifier columns were present.

The generated corpus is balanced across Quality, Manufacturing, Inventory,
Sales, Supply Chain, and Yield. Every artifact includes:

- A stable `SEM-###` artifact ID.
- The fully qualified Databricks source table.
- The profile timestamp and source system.
- Narrative text, source-grounded values, and tabular data.
- Full-table row counts, date coverage, data-quality facts, measure ranges, and
  bounded representative-sample observations.
- Clearly labeled recommended follow-up actions, kept separate from source facts.
- Charts, lineage diagrams, tables, bullets, and typed source schemas.
- At least four Word pages with five tables and two visuals, eight PowerPoint
  slides (with schema pagination when needed), or seven named Excel worksheets
  with a chart and conditional formatting.

SharePoint metadata columns are `ArtifactId`, `KnowledgeCategory`,
`SourceTable`, `SourceSystem`, and `ProfileGeneratedAt`. The Search data source
requests these columns with `additionalColumns`, and each projected chunk
inherits them.

## Repository layout

```text
.
|-- README.md
|-- LICENSE
|-- requirements.txt
|-- config/
|   |-- deployment.json                 # non-secret deployment configuration
|   |-- profile-agent-prompt.md
|   |-- foundry-agent-instructions.md
|   `-- search-evaluation.cases
|-- docs/
|   `-- deployment-evidence.md
|-- data/
|   `-- semiconductor_profile.json       # generated, ignored
|-- corpus/
|   |-- manifest.json                    # generated, ignored
|   `-- <category>/*.docx|*.pptx|*.xlsx  # generated, ignored
`-- scripts/
    |-- deploy_staged.ps1
  |-- deployment_config.ps1
  |-- deployment_config.py
    |-- evaluate_search.ps1
    |-- fetch_semiconductor_profile.py
    |-- generate_corpus.py
    |-- promote_search_index.ps1
    |-- provision_foundry_agent.ps1
    |-- provision_search.ps1
    |-- provision_sharepoint.ps1
    |-- submit_search_feedback.ps1
    |-- validate_corpus.py
    `-- validate_search.ps1
```

  ## Configuration

  `config/deployment.json` is the single source of truth for non-secret
  deployment values. Scripts accept `-ConfigPath` or `--config` to select a
  different environment file, and explicit command-line arguments remain
  available as one-run overrides.

  | README placeholder | Configuration key |
  | --- | --- |
  | `{Tenant Id}` / `{Subscription Id}` / `{Resource Group}` | `azure.*` |
  | `{Production Library}` | `sharePoint.productionLibraryName` |
  | `{Search Service}` / `{Search Index Alias}` | `search.serviceName` / `search.indexAliasName` |
  | `{Search SKU}` / `{Azure Region}` | `search.sku` / `azure.location` |
  | `{Partition Count}` / `{Replica Count}` | `search.partitionCount` / `search.replicaCount` |
  | `{Chunk Size}` / `{Chunk Overlap}` | `search.chunkSize` / `search.chunkOverlap` |
  | `{Chunk Unit}` / `{Tokenizer}` / `{Corpus Language}` | `search.chunkUnit` / `search.tokenizer` / `search.corpusLanguage` |
  | `{Embedding Deployment}` / `{Embedding Dimensions}` | `search.embeddingDeployment` / `search.embeddingDimensions` |
  | `{Vector Algorithm}` / `{Vector Metric}` | `search.vectorAlgorithmKind` / `search.vectorMetric` |
  | `{Indexer Schedule}` | `search.scheduleInterval` |
  | `{Databricks Catalog}` / `{Databricks Schema}` | `databricks.catalog` / `databricks.schema` |
  | `{Profile Source Agent}` | `foundry.profileSource.agentName` |
  | `{Foundry Agent}` / `{Knowledge Source}` / `{Knowledge Base}` | `foundry.knowledgeAgent.*` |
  | `{Expected Document Count}` / `{Bootstrap Document Count}` | `corpus.*Documents` |
  | `{Search Service API Version}` | `apiVersions.searchService` |

  No secret, access token, password, Search key, or connection credential belongs
  in the config file. Runtime secrets remain in process memory only.

## Prerequisites

- Windows PowerShell 7 and Azure CLI.
- Python 3.13 or a compatible supported Python 3 release.
- Azure access to subscription `{Subscription Id}`.
- An active Azure PowerShell context for that subscription (`Get-AzContext`).
- Microsoft 365 administrator access in tenant `{Tenant Id}`.
- Permission to create Microsoft 365 groups, SharePoint lists, Entra
  applications, app-role grants, role assignments, and Search resources.
- Registration for the [SharePoint indexer preview](https://aka.ms/azure-cognitive-search/indexer-preview).

The deployment uses the signed-in Azure PowerShell administrator to bootstrap
a temporary Graph provisioner. That app's short-lived password exists only in
process memory and the app is deleted in a `finally` block after upload. The
standing Search ingestion app has no passwords or certificates and uses a
managed-identity federated credential. No password, client secret, Search key,
or token is stored in the repository or `.state/` files.

## Deploy the solution

### 1. Create a Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Fetch a current Databricks profile

```powershell
.\.venv\Scripts\python.exe scripts\fetch_semiconductor_profile.py
```

This invokes `{Profile Source Agent}`. It issues bounded, read-only
queries through the private Databricks MCP server and validates the returned
JSON shape before writing the profile.

### 3. Run the recommended staged deployment

```powershell
.\scripts\deploy_staged.ps1
```

This is the default end-to-end workflow. It executes the requested order:

1. Provision or reuse the SharePoint site, library, folders, and metadata.
2. Generate `{Bootstrap Document Count}` bootstrap files, distributed across
  the configured formats and semiconductor domains.
3. Upload those files to a dedicated bootstrap library, create isolated
   bootstrap Search resources, validate them, and run the routing suite.
4. Generate and structurally validate the configured replacement corpus
   before changing the production library.
5. Upload the full set, build a versioned candidate index without touching the
   current index, validate coverage and routing, then atomically promote it
  through `{Search Index Alias}`.

The previous physical index is retained for rollback. The standing feedback
index is preserved across document generations. Before production files are
replaced, the currently served generation's indexer is disabled. After alias
promotion, only the promoted indexer's schedule remains enabled; rollback
indexes therefore remain immutable snapshots.
Use `-RefreshProfile` to query Databricks through the existing Foundry agent
before generation.

### 4. Run individual stages

Generate and validate the configured document count:

```powershell
.\.venv\Scripts\python.exe scripts\generate_corpus.py
.\.venv\Scripts\python.exe scripts\validate_corpus.py
```

The validator opens every Open XML package and checks format counts,
provenance, page/slide/sheet structure, tables, charts, and diagrams.

### 5. Authenticate Azure PowerShell

```powershell
Connect-AzAccount -Tenant '{Tenant Id}'
Set-AzContext -Subscription '{Subscription Id}'
```

The signed-in account needs `Application.ReadWrite.All` and
`AppRoleAssignment.ReadWrite.All` in its Microsoft Graph token, plus Azure
permissions to read Search keys and manage role assignments. Complete
credentials and MFA only on the Microsoft sign-in page.

### 6. Provision SharePoint and upload the corpus

```powershell
.\scripts\provision_sharepoint.ps1
```

The script is idempotent by group alias, library name, column internal name,
folder name, and file path. Re-running replaces same-path corpus files and
updates metadata instead of creating duplicate documents. It creates a
temporary app with `Group.ReadWrite.All`, `Sites.ReadWrite.All`,
`Sites.Manage.All`, and `Files.ReadWrite.All` only for the transaction, then
deletes it whether the transaction succeeds or fails.

Use `-SiteOnly` to provision metadata before generating files. Use
`-ExpectedDocuments` with a staged manifest and `-PruneMissingDocuments` to
make SharePoint exactly match that manifest before upload.

The staged workflow prunes only the isolated bootstrap library. It fully
generates, validates, and preflights the production corpus before upload.
Unexpected stale production files cause the exact parent/artifact gate to fail
before alias promotion rather than being destructively removed up front.

### 7. Provision the direct Search pipeline

```powershell
.\scripts\provision_search.ps1
```

The script creates or updates the Entra ingestion app, federated credential,
Graph application permissions, versioned chunk index, skillset, SharePoint data
source, scheduled indexer, and independent `{Feedback Index}`.
Search admin keys are read only into process memory for control-plane setup and
are then discarded. `-RecreateIndex` deletes and recreates only the document
index and indexer; feedback and identity resources remain intact.

### 8. Validate indexing and retrieval

Wait for the indexer to complete, then run:

```powershell
.\scripts\validate_search.ps1
```

Validation requires all of the following:

- The most recent indexer run succeeded with zero failed items.
- The chunk index contains `{Expected Document Count}` distinct parent IDs.
- Every configured Office format facet is present.
- Every configured knowledge category is present.
- A semantic hybrid query with query-time vectorization returns results.

The verified deployment contains `{Expected Document Count}` distinct parent
documents and `{Indexed Chunk Count}` projected chunks. All configured formats
and categories are present. The configured validation query returned a semantic
result linked to an original SharePoint document.

### 9. Provision the Foundry IQ agent

```powershell
.\scripts\provision_foundry_agent.ps1
```

Following the Microsoft guidance for [connecting Foundry IQ to Foundry Agent
Service](https://learn.microsoft.com/azure/foundry/agents/how-to/foundry-iq-connect),
the script enables dual Search authentication, applies least-privilege managed
identity roles, creates or updates `{Knowledge Source}` and `{Knowledge Base}`,
creates a project-managed-identity MCP connection, versions `{Foundry Agent}`,
and runs one citation-bearing smoke query. Confirmed state is written to the
configured Foundry state path under `.state/`.

## Azure AI Search design

### Direct SharePoint indexing

The [SharePoint in Microsoft 365 indexer](https://learn.microsoft.com/azure/search/search-how-to-index-sharepoint-online)
uses the preview `sharepoint` data-source type and `useQuery` container.
`includeLibrary` limits crawling to `{Production Library}`, and
`additionalColumns` brings corpus lineage into the enrichment tree. The
indexer accepts the formats in `corpus.formats` and runs on `{Indexer Schedule}`
for incremental additions, updates, and deletes.

### Chunking

The [Text Split skill](https://learn.microsoft.com/azure/search/cognitive-search-skill-textsplit)
uses token-aware page splitting. The values below come from
`config/deployment.json`:

| Setting | Value | Rationale |
| --- | --- | --- |
| Unit | `{Chunk Unit}` | Keeps chunks aligned with embedding-model input units |
| Tokenizer | `{Tokenizer}` | Matches the selected embedding family |
| Maximum length | `{Chunk Size}` | Bounds each embedding input |
| Overlap | `{Chunk Overlap}` | Carries context across boundaries |
| Language | `{Corpus Language}` | Matches the generated corpus |

The overlap improves continuity for table-adjacent narrative and sections
that cross chunk boundaries. All pages are retained; `maximumPagesToTake` is
not set.

### Index projection

The recommended [index projection](https://learn.microsoft.com/azure/search/search-how-to-define-index-projections)
single-index RAG pattern is used. Each chunk repeats its
parent's title, SharePoint URL, file metadata, corpus category, and Databricks
lineage. `projectionMode` is `skipIndexingParentDocuments`, which avoids extra
parent rows with null chunk fields. The generated projected key supports
incremental child updates and deletion tracking.

### Vector search

- Model and deployment: `{Embedding Model}` / `{Embedding Deployment}`.
- Dimensions: `{Embedding Dimensions}` in both the embedding skill and vector field.
- Algorithm and metric: `{Vector Algorithm}` with `{Vector Metric}` similarity.
- HNSW parameters: `{HNSW M}`, `{HNSW EF Construction}`, `{HNSW EF Search}`.
- Query vectorizer: the same model and deployment as indexing.
- Authentication: Search system-assigned managed identity.

Matching model, deployment, and dimensions between indexing and query time is
required for meaningful similarity scores. For a higher-volume production
deployment, use separate deployments of the same embedding model for indexing
and query traffic so each has independent TPM capacity and telemetry.

### Hybrid and semantic retrieval

The index supports keyword, vector, [hybrid](https://learn.microsoft.com/azure/search/hybrid-search-overview),
filtering, faceting, and [semantic ranking](https://learn.microsoft.com/azure/search/semantic-search-overview).
`title` is the semantic title field, `chunk` is the prioritized content field,
and category/source table are semantic keyword fields. Foundry IQ plans and
executes retrieval against this index; exact identifiers benefit from lexical
matching while narrative questions benefit from vectors and semantic reranking.

### Partitions

The POC uses `{Partition Count}` partition(s). Partitions provide index storage and indexing
throughput; the application does not manually assign documents to partitions.
Azure AI Search distributes index data internally. Increase partitions only
after measuring index size, ingestion throughput, throttling, and query
latency. Search units are calculated as:

$$
\text{Search units} = \text{replicas} \times \text{partitions}
$$

For this `{Expected Document Count}`-document corpus, additional partitions
would add cost without a measured capacity benefit. Generated deployment
evidence records `{Indexed Chunk Count}`, `{Index Storage Size}`, and
`{Vector Index Size}` without baking one environment's measurements into this
document.

### Replicas and replication

The POC uses `{Replica Count}` replica(s) to minimize cost and has no
availability SLA. Azure
AI Search automatically copies index data across configured replicas; the
solution does not implement custom file or index replication.

- Use at least two replicas for a production read-only/query SLA.
- Use at least three replicas for a production read-write SLA while indexing.
- Keep at least one partition unless storage or throughput measurements show
  that more are required.
- Use a second Search service and external traffic routing only when a
  multi-region disaster-recovery requirement justifies it.

## Security model

The Search service has a system-assigned managed identity. It receives only
the configured model-inference role on the embedding resource and
`Cognitive Services User` on the Foundry IQ model provider. The Foundry
project identity receives `Search Index Data Reader` on Search. See
[Search RBAC](https://learn.microsoft.com/azure/search/search-security-rbac)
and [Foundry RBAC](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry).

The dedicated Entra ingestion application has Microsoft Graph application
permissions `Files.Read.All` and `Sites.Read.All`, as required by the standard
SharePoint document-library indexer flow. Tenant admin consent is represented
by app-role assignments. A federated identity credential trusts the Search
managed identity, eliminating a client secret from the Search data source.

For a broader production rollout, reassess whether the current preview API and
tenant configuration support a site-scoped `Sites.Selected` design. Preserve
SharePoint ACL metadata and enforce query-time security trimming before
placing permission-sensitive documents in the corpus.

## Operations and validation

### Refresh data

1. Refresh the Databricks profile.
2. Regenerate and validate the corpus.
3. Re-run the SharePoint provisioning script to replace files and metadata.
4. Let the scheduled indexer run, or invoke its `/run` endpoint.
5. Run the Search validation script.

Avoid renaming SharePoint folders after indexing. The preview indexer treats a
renamed folder as new content, which can disrupt incremental behavior.

### Monitor

- Review indexer execution history and warnings in the Search portal.
- Enable Azure Monitor diagnostic settings for Search query and indexer logs.
- Monitor embedding deployment TPM, latency, throttling responses, and failures.
- Alert on failed indexer runs and unexpected drops in unique parent count.
- Use exponential backoff for application query retries. Indexers include
  built-in retry and resume behavior for transient source failures.

### Rebuild

Azure AI Search is not the primary data store. If the index is lost, recreate
the schema and rerun the indexer from SharePoint. The generated corpus can also
be deterministically recreated from a validated Databricks profile.

Use the following command for a clean full rebuild without deleting feedback:

```powershell
.\scripts\provision_search.ps1 -RecreateIndex
.\scripts\validate_search.ps1
```

For a zero-downtime staged replacement, prefer `deploy_staged.ps1`. It validates
a versioned candidate and switches the stable alias only after every gate passes.

## Relevance evaluation and feedback

The fixed test set in `config/search-evaluation.cases` contains
`{Evaluation Case Count}` questions spanning the configured semiconductor
domains. Each case declares its expected category and unqualified table name;
the evaluator builds the fully qualified name from the configured Databricks
catalog and schema. The evaluator runs keyword and vector
retrieval together, applies semantic reranking, and records:

- Category routing@1.
- Source-table routing@1 and routing@3.
- Source-table routing mean reciprocal rank (MRR).
- Average and p95 request latency.
- Ranked result IDs, citations, vector/RRF scores, and semantic reranker scores.

Run it with:

```powershell
.\scripts\evaluate_search.ps1
```

The latest generated report records `{Category Routing At 1}`,
`{Source Table Routing At 1}`, `{Source Table Routing At 3}`, routing MRR,
average latency, and p95 latency.
These are routing metrics: they prove the right domain/table reaches the top,
not that every returned passage is fully relevant. Any change to chunking,
vector tuning, or semantic ranking should be compared against the configured
thresholds before promotion.

Applications can write an explicit relevance judgment with:

```powershell
.\scripts\submit_search_feedback.ps1 `
  -Query '<user query>' `
  -ChunkId '<returned chunk_id>' `
  -ParentId '<returned parent_id>' `
  -DocumentUrl '<returned document_url>' `
  -Category '<returned category>' `
  -SourceTable '<returned source_table>' `
  -Rating <1-to-5 rating> `
  -Relevant $true `
  -Comment '<optional reason>'
```

Feedback is isolated from source chunks, tagged with the physical index
generation and retrieval timestamp, and filtered to the generation under test.
It survives document-index rebuilds and cannot be mistaken for source content.
Review false positives and misses by query/category/source table, add graded
artifact/chunk judgments for passage-level relevance, then compare chunking or
ranking candidates against the fixed suite before deployment. Do not train on
raw thumbs-up/down data without review.

The feedback write path is validated with a generation-scoped judgment and a
successful Search indexing response.

## Foundry agent integration

The deployed `{Foundry Agent}` has one MCP tool: the Foundry IQ
`knowledge_base_retrieve` operation exposed by `{Knowledge Base}`. The
knowledge base uses `{Knowledge Source}` to query the promoted Azure AI Search
index, plan subqueries, rerank passages, synthesize an answer, and return
source references. Agent instructions require each Foundry IQ annotation to be
accompanied by a clickable `document_url` link to the underlying SharePoint
document; the deployment smoke test rejects an answer without one. See
[create a search-index knowledge source](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-search-index)
and [create a knowledge base](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-knowledge-base).

The profile-source agent remains separate. It queries Databricks through the
private MCP connection to regenerate the bounded source profile; it is not a
runtime tool on `{Foundry Agent}`. Retrieved Search passages preserve
`document_url`, `title`, `artifact_id`, `source_table`, and
`profile_generated_at`, allowing the agent to cite SharePoint and explain data
freshness without claiming that the documents are live Databricks results.

## Sample prompts

Use these prompts in the [deployed Foundry IQ agent](https://ai.azure.com/nextgen/r/z4JFcKi6SXqhhApS8YMKqQ,m365-myaacoub,,foundry-myaacoub,proj-default/build/agents/sharepoint-agent/build?tid=12a4b86b-e64c-43f9-af05-d9130a72dfd2):

1. Which wafer-yield results are below target for AI accelerators? Cite the SharePoint documents and include the Databricks source table.
2. Compare average, best, worst, and target wafer yield by process node. Separate source facts from recommended follow-up actions.
3. Which fabrication processes show high defect PPM from pattern, contamination, or etch defects? Include artifact IDs and citations.
4. Summarize high-severity semiconductor defects by fab and process node, and identify any limitations in the indexed sample.
5. Compare fab production cycle time, wafers started, wafers completed, and good dies. Cite each supporting document.
6. Find inventory positions below reorder point with limited days of supply. Group the answer by warehouse region.
7. Compare semiconductor revenue, units sold, average selling price, and gross margin by region or customer segment.
8. Which suppliers show high risk, long lead times, weak on-time delivery, or low quality scores for wafers and substrates?
9. Trace one claim about AI accelerator yield back to its SharePoint URL, artifact ID, Databricks source table, and profile timestamp.
10. Produce a cross-domain executive summary of yield, quality, production, inventory, sales, and supply-chain risk. Cite every section and state where evidence is insufficient.

## Preview limitations

The SharePoint Online indexer and `{Search Service API Version}` are offered
under Azure preview terms and are not recommended for production without a
risk review. Current documented limitations include:

- No private endpoint support for the SharePoint indexer.
- No support for tenants with Microsoft Entra Conditional Access enabled.
- Preview ACL synchronization and sensitivity-label behavior.
- Folder renames can break incremental indexing assumptions.
- User-encrypted and password-protected files are unsupported.

This tenant showed a Conditional Access challenge during interactive Graph
administration. The user requested proceeding with the preview indexer, and
the direct application-authenticated indexer completed successfully for
`{Expected Document Count}` files with zero failures. Because Microsoft still
documents Conditional Access as unsupported for this preview, repeat the
end-to-end validation after any tenant policy or indexer API change.

## Cost and production scaling

The recurring POC costs are the configured Search SKU and embedding tokens.
SharePoint licensing and the existing Foundry/Databricks resources are outside
this repository's incremental Search estimate.

Before production:

- Scale to three replicas if queries and scheduled indexing require the
  read-write SLA.
- Keep one partition until measured storage or indexing throughput requires
  more.
- Separate indexing and query embedding deployments.
- Enable diagnostic settings, budgets, alerts, and quota monitoring.
- Load-test hybrid queries with representative concurrency and filters.
- Review accumulated relevance feedback and require evaluation thresholds
  before accepting ranking, schema, or chunking changes.
- Review preview, Conditional Access, network, ACL, and compliance constraints.

## Additional references

- [SharePoint in Microsoft 365 indexer](https://learn.microsoft.com/azure/search/search-how-to-index-sharepoint-online)
- [What is Foundry IQ?](https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-foundry-iq)
- [Connect Foundry IQ to Foundry Agent Service](https://learn.microsoft.com/azure/foundry/agents/how-to/foundry-iq-connect)
- [Create a search-index knowledge source](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-search-index)
- [Create an Azure AI Search knowledge base](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-knowledge-base)
- [Microsoft Foundry prompt agents](https://learn.microsoft.com/azure/foundry/agents/quickstarts/prompt-agent)
- [Foundry role-based access control](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry)
- [Azure AI Search role-based access control](https://learn.microsoft.com/azure/search/search-security-rbac)
- [Integrated vectorization](https://learn.microsoft.com/azure/search/vector-search-integrated-vectorization)
- [Chunk documents for vector search](https://learn.microsoft.com/azure/search/vector-search-how-to-chunk-documents)
- [Text Split skill](https://learn.microsoft.com/azure/search/cognitive-search-skill-textsplit)
- [Azure OpenAI embedding skill](https://learn.microsoft.com/azure/search/cognitive-search-skill-azure-openai-embedding)
- [Configure a vectorizer](https://learn.microsoft.com/azure/search/vector-search-how-to-configure-vectorizer)
- [Define index projections](https://learn.microsoft.com/azure/search/search-how-to-define-index-projections)
- [Hybrid search](https://learn.microsoft.com/azure/search/hybrid-search-overview)
- [Semantic ranking](https://learn.microsoft.com/azure/search/semantic-search-overview)
- [Search capacity planning](https://learn.microsoft.com/azure/search/search-capacity-planning)
- [Reliability in Azure AI Search](https://learn.microsoft.com/azure/reliability/reliability-ai-search)
- [Search managed identities](https://learn.microsoft.com/azure/search/search-how-to-managed-identities)
- [Search monitoring](https://learn.microsoft.com/azure/search/search-monitor-enable-logging)
- [Azure AI Search security overview](https://learn.microsoft.com/azure/search/search-security-overview)

## License

Copyright (c) 2026 Michael Yaacoub @ Microsoft. This project is available under
the [MIT License](LICENSE).