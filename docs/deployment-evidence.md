# Deployment Evidence

Snapshot captured on 2026-09-15 after staged candidate validation and alias
promotion. This file contains no access tokens, API keys, passwords, or private
Databricks rows.

## Resources

- SharePoint site: `https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub`
- Production library: `Semiconductor Knowledge`
- Isolated bootstrap library: `Semiconductor Knowledge Bootstrap`
- Search service: `semiconductor-search-myaacoub`
- Stable Search alias: `semiconductor-knowledge`
- Promoted physical index: `semiconductor-20260915214135-knowledge-chunks`
- Bootstrap physical index: `semiconductor-bootstrap-knowledge-chunks`
- Feedback index: `semiconductor-search-feedback`
- Embedding deployment: `text-embedding-3-small`

## Corpus Gate

- Source documents: 100
- DOCX: 34
- PPTX: 33
- XLSX: 33
- Domains: Quality, Manufacturing, Inventory, Sales, Supply Chain, Yield
- Rich-document validator: passed all 100 packages
- Rendered full-table KPI reconciliation: passed all 100 packages

## Search Gate

- Unique SharePoint parents: 100
- Unique artifact IDs: 100
- Projected chunks: 289
- Chunks missing lineage/citation metadata: 0
- Indexer failures: 0
- Indexer warnings: 0
- Hybrid semantic/vector smoke query: passed with a SharePoint citation

## Routing Gate

The fixed suite contains 12 hybrid semantic/vector queries, two per domain.
These metrics describe routing to the expected category and source table, not
graded passage relevance.

- Category routing@1: 1.0
- Source-table routing@1: 1.0
- Source-table routing@3: 1.0
- Source-table routing MRR: 1.0
- Latest average latency: 394.3 ms
- Latest P95 latency: 792 ms
- Generation-scoped feedback judgments: 1 relevant, 0 not relevant

## Capacity Review

- Search tier: Basic
- Partitions: 1
- Replicas: 1
- Measured promoted-index storage: 5,068,310 bytes (approximately 5.07 MB)
- Measured promoted vector index: 1,797,128 bytes (approximately 1.80 MB)

One partition remains appropriate for this POC. One replica minimizes cost but
does not provide a production SLA. Use at least two replicas for a query-only
SLA or three replicas for a query-and-indexing SLA.

## Security Gate

- SharePoint is the sole document source; no Blob staging exists.
- Search uses a system-assigned managed identity for embeddings.
- The standing ingestion app has `Files.Read.All` and `Sites.Read.All` only.
- The standing ingestion app has no password or certificate credentials.
- Its managed-identity federation tuple is reconciled to the current Search identity.
- Temporary SharePoint provisioner apps are explicitly cleaned up and verified.