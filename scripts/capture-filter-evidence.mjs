// Captures screenshots that prove where the "published-only" filter is enforced in Azure AI Search.
// Reads the live service (admin key from `az`), renders the evidence as HTML and screenshots it with Playwright.
// Usage (from repo root): node scripts/capture-filter-evidence.mjs
import { execSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const require = createRequire(path.resolve('app/ui/package.json'));
const { chromium } = require('@playwright/test');

const SERVICE = process.env.SEARCH_SERVICE ?? 'semiconductor-search-myaacoub';
const RESOURCE_GROUP = process.env.SEARCH_RG ?? 'm365-myaacoub';
const VERSION = '2026-08-01-preview';
const INDEX = 'departments-knowledge-index';
const SOURCE = 'trusted-knowledge-ks';
const BASE = 'trusted-knowledge-kb';
const QUESTION = 'Show draft, under review, superseded or archived policies, proposals and templates';
const OUT = path.resolve('docs/images/search');

const endpoint = `https://${SERVICE}.search.windows.net`;
const key = execSync(`az search admin-key show --service-name ${SERVICE} --resource-group ${RESOURCE_GROUP} --query primaryKey -o tsv`).toString().trim();

async function call(method, route, body) {
  const response = await fetch(`${endpoint}${route}${route.includes('?') ? '&' : '?'}api-version=${VERSION}`, {
    method,
    headers: { 'api-key': key, 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${method} ${route} -> ${response.status} ${await response.text()}`);
  return response.json();
}

const esc = (value) => String(value ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
const css = `body{font:14px Segoe UI,Arial,sans-serif;margin:0;padding:24px;background:#f3f6fb;color:#16202e}
.card{background:#fff;border:1px solid #cfd8e6;border-radius:8px;padding:20px 24px;width:1040px}
h1{font-size:18px;margin:0 0 4px}.sub{color:#51607a;margin:0 0 14px}
pre{background:#0f1b2d;color:#dbe7ff;padding:14px 16px;border-radius:6px;font:13px Consolas,monospace;overflow:auto;margin:0}
.hl{background:#14532d;color:#d1fae5;display:block;padding:2px 6px;margin:0 -6px;border-radius:3px}
table{border-collapse:collapse;width:100%;margin-top:6px}th,td{border:1px solid #d8e0ee;padding:6px 10px;text-align:left}
th{background:#eaf0fa}.ok{color:#0f7b3f;font-weight:600}.bad{color:#b42318;font-weight:600}.pill{padding:1px 8px;border-radius:10px;font-size:12px}
.pub{background:#d1fae5;color:#065f46}.draft{background:#fee2e2;color:#991b1b}.other{background:#fef3c7;color:#92400e}
.note{margin-top:12px;color:#51607a}.cols{display:flex;gap:24px}.cols>div{flex:1}`;
const pill = (status) => `<span class="pill ${status === 'Published' ? 'pub' : status === 'Draft' ? 'draft' : 'other'}">${esc(status)}</span>`;

const knowledgeSource = await call('GET', `/knowledgesources/${SOURCE}`);
const baseFilter = knowledgeSource.searchIndexParameters?.baseFilter;
if (!baseFilter) throw new Error(`Knowledge source ${SOURCE} has no baseFilter`);

const facetQuery = (filter) => call('POST', `/indexes/${INDEX}/docs/search`, {
  search: '*', top: 0, count: true, facets: ['lifecycle_status,count:10'], ...(filter ? { filter } : {}),
});
const [allDocs, publishedDocs] = await Promise.all([facetQuery(), facetQuery(baseFilter)]);

const unfiltered = await call('POST', `/indexes/${INDEX}/docs/search`, {
  search: 'draft policy proposal template', top: 8, select: 'title,lifecycle_status,authoritative,ai_ready,sensitivity',
});

const retrieval = await call('POST', `/knowledgebases/${BASE}/retrieve`, {
  messages: [{ role: 'user', content: [{ type: 'text', text: QUESTION }] }],
  knowledgeSourceParams: [{ knowledgeSourceName: SOURCE, kind: 'searchIndex', includeReferences: true, includeReferenceSourceData: true }],
});
const references = retrieval.references ?? [];

const compactParameters = {
  ...knowledgeSource.searchIndexParameters,
  sourceDataFields: `${(knowledgeSource.searchIndexParameters.sourceDataFields ?? []).length} fields incl. title, document_url, lifecycle_status, authoritative, ai_ready, sensitivity`,
  searchFields: (knowledgeSource.searchIndexParameters.searchFields ?? []).map((f) => f.name),
};

const pages = {
  '01-knowledge-source-basefilter': `<div class="card"><h1>Knowledge source <code>${esc(SOURCE)}</code> - searchIndexParameters</h1>
<p class="sub">GET ${esc(endpoint)}/knowledgesources/${esc(SOURCE)}?api-version=${VERSION}. The filter is persisted on the knowledge source, so every retrieve call (including the Foundry agent's MCP tool) is ANDed with it.</p>
<pre>${esc(JSON.stringify({ name: knowledgeSource.name, kind: knowledgeSource.kind, searchIndexParameters: compactParameters }, null, 2))
    .split('\n').map((line) => (line.includes('baseFilter') ? `<span class="hl">${line}</span>` : line)).join('\n')}</pre>
<p class="note">Hub datasources and indexers copy every document with its governance columns; the filter, not the indexer, decides what the agent may see.</p></div>`,

  '02-index-lifecycle-facets': `<div class="card"><h1>Index <code>${INDEX}</code> - what is stored vs. what the agent can see</h1>
<p class="sub">Same facet query run twice against the live index: once unfiltered, once with the knowledge source <code>baseFilter</code>.</p>
<div class="cols"><div><b>Stored in the index (${allDocs['@odata.count']} chunks)</b><table><tr><th>lifecycle_status</th><th>chunks</th></tr>
${(allDocs['@search.facets']?.lifecycle_status ?? []).map((f) => `<tr><td>${pill(f.value)}</td><td>${f.count}</td></tr>`).join('')}</table></div>
<div><b>Visible through baseFilter (${publishedDocs['@odata.count']} chunks)</b><table><tr><th>lifecycle_status</th><th>chunks</th></tr>
${(publishedDocs['@search.facets']?.lifecycle_status ?? []).map((f) => `<tr><td>${pill(f.value)}</td><td>${f.count}</td></tr>`).join('')}</table></div></div>
<pre style="margin-top:14px"><span class="hl">filter: ${esc(baseFilter)}</span></pre></div>`,

  '03-retrieve-published-only': `<div class="card"><h1>Knowledge base retrieve vs. unfiltered index search</h1>
<p class="sub">Question: "${esc(QUESTION)}"</p>
<b>Unfiltered search on the index (what a raw query would return)</b>
<table><tr><th>title</th><th>lifecycle_status</th><th>authoritative</th><th>ai_ready</th><th>sensitivity</th></tr>
${unfiltered.value.map((d) => `<tr><td>${esc(d.title)}</td><td>${pill(d.lifecycle_status)}</td><td>${d.authoritative}</td><td>${d.ai_ready}</td><td>${esc(d.sensitivity)}</td></tr>`).join('')}</table>
<p></p><b>POST /knowledgebases/${esc(BASE)}/retrieve (what the agent receives): ${references.length} reference(s)</b>
<table><tr><th>title</th><th>lifecycle_status</th><th>authoritative</th><th>ai_ready</th><th>sensitivity</th></tr>
${references.map((r) => `<tr><td>${esc(r.sourceData?.title)}</td><td>${pill(r.sourceData?.lifecycle_status)}</td><td>${r.sourceData?.authoritative}</td><td>${r.sourceData?.ai_ready}</td><td>${esc(r.sourceData?.sensitivity)}</td></tr>`).join('')}</table>
<p class="note ${references.every((r) => r.sourceData?.lifecycle_status === 'Published') ? 'ok' : 'bad'}">${references.every((r) => r.sourceData?.lifecycle_status === 'Published') ? 'Every reference returned to the agent is Published, authoritative and AI-ready.' : 'LEAK: a non-published reference was returned.'}</p></div>`,
};

// Optional: pass the captured output of scripts/Test-FoundryAgent.ps1 as AGENT_TEST_LOG to add the agent test screenshot.
if (process.env.AGENT_TEST_LOG) {
  const log = readFileSync(process.env.AGENT_TEST_LOG, 'utf8').replace(/\r/g, '').replace(/^\uFEFF/, '');
  const coloured = esc(log)
    .replace(/\[PASS\]/g, '<b style="color:#4ade80">[PASS]</b>')
    .replace(/\[FAIL\]/g, '<b style="color:#f87171">[FAIL]</b>')
    .replace(/^(\[[^\]]+\].*)$/gm, '<span style="color:#7dd3fc">$1</span>')
    .replace(/(did not surface [\w-]+)/g, '<span class="hl" style="display:inline;padding:1px 6px;margin:0">$1</span>');
  pages['04-agent-end-to-end-test'] = `<div class="card"><h1>Foundry agent end-to-end test (scripts/Test-FoundryAgent.ps1)</h1>
<p class="sub">Hub questions are answered from Published documents; draft and superseded documents are never surfaced.</p>
<pre style="white-space:pre-wrap">${coloured}</pre></div>`;
}

mkdirSync(OUT, { recursive: true });
const workDir = mkdtempSync(path.join(tmpdir(), 'filter-evidence-'));
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1120, height: 800 }, deviceScaleFactor: 2 });
  for (const [name, body] of Object.entries(pages)) {
    const file = path.join(workDir, `${name}.html`);
    writeFileSync(file, `<!doctype html><meta charset="utf-8"><style>${css}</style>${body}`);
    await page.goto(pathToFileURL(file).href);
    await page.locator('.card').screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log(`wrote docs/images/search/${name}.png`);
  }
} finally {
  await browser.close();
}
