import { test, expect, Page } from '@playwright/test';
import { configureBrowser, documentId, signIn } from '../fixtures/signed-in';
import type { DocumentDetail, NotificationItem } from '../../src/app/core/api/models/api.models';
import prompts from '../fixtures/test-only-agent-prompts.json';

const libraryId = documentId.split('.')[0];
const library = { id: libraryId, libraryId, title: 'Test Knowledge', rootPath: '/Test', webUrl: 'https://contoso.sharepoint.com/Test', hasUniquePermissions: false };
const document: DocumentDetail = {
  id: documentId, libraryId, libraryTitle: library.title, name: 'Test guide.docx', title: 'Test guide',
  kind: 'file', path: '/Test/Test guide.docx', webUrl: 'https://contoso.sharepoint.com/Test/guide.docx',
  hasUniquePermissions: false, modified: '2026-10-21', size: 100, artifactId: 'TEST-1',
  knowledgeCategory: 'Engineering', lifecycleStatus: 'Published', authoritative: true, aiReady: true,
  reviewDate: '2026-10-01', expirationDate: '2026-10-01', effectiveDate: '2026-01-01',
  documentType: 'Guide', productFamily: null, processArea: null, sensitivity: null,
  dataQualityStatus: 'Validated', conflictStatus: null, trustScore: 90,
  knowledgeOwner: 'owner@contoso.com', ownerDisplayName: 'Test Owner', duplicateOf: null,
  businessUnit: null, sourceSystem: null, supersedesDocument: null, trustReasons: [],
  conflictWith: [], contentHash: null, lastValidatedDate: null, liveDuplicateRoles: [], liveExpiry: null,
};
const expiry = {
  expired: true, expiredBy: ['metadata'], expirationDate: '2026-10-01', daysPastExpiration: 27,
  reviewDate: null, reviewOverdue: false, overdueBy: [], daysOverdue: null, textDates: [],
};

async function setup(page: Page): Promise<void> {
  const outbox: NotificationItem[] = [];
  await configureBrowser(page, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const endpoint = url.pathname.replace('/api/v1', '');
    if (request.headers()['authorization'] !== 'Bearer test-only-access-token') {
      await route.fulfill({ status: 401, json: { error: { code: 'unauthorized' } } });
      return;
    }
    const finding = { id: 'expired-documents', title: 'Expired documents', severity: 'high', count: 1, byLibrary: { [library.title]: 1 } };
    const metrics = [{ key: 'totalIndexedDocuments', label: 'Total documents', value: 1 }];
    const responses: Record<string, unknown> = {
      '/policy': { hygiene: { metrics } },
      '/hygiene': { asOfDate: '2026-10-28', metrics, findings: [finding] },
      '/hygiene/findings/expired-documents': { ...finding, documents: [document] },
      '/documents': { items: [document], page: 1, pageSize: 25, total: 1, totalPages: 1, knowledgeCategories: ['Engineering'] },
      [`/documents/${documentId}`]: document,
      [`/documents/${documentId}/preview`]: { kind: 'docx', name: 'Test guide.docx', blocks: [{ kind: 'paragraph', text: 'Test guide content' }], tables: [] },
      [`/documents/${documentId}/content`]: 'Test guide content',
      '/site': {
        name: 'Test site',
        webUrl: 'https://contoso.sharepoint.com/sites/test',
        serverRelativeUrl: '/sites/test',
        hasUniquePermissions: false,
        libraryCount: 1,
        selectedSite: {
          siteId: 'default',
          displayName: 'Test site',
          function: null,
          siteUrl: 'https://contoso.sharepoint.com/sites/test',
          serverRelativeUrl: '/sites/test',
        },
        availableSites: [
          {
            siteId: 'default',
            displayName: 'Test site',
            function: null,
            siteUrl: 'https://contoso.sharepoint.com/sites/test',
            serverRelativeUrl: '/sites/test',
          },
        ],
      },
      '/site/libraries': { items: [library], total: 1 },
      [`/site/libraries/${libraryId}/children`]: {
        library, folder: null, items: [{ ...document, childCount: null, created: '2026-01-01' }], total: 1, truncated: false,
      },
      [`/items/${documentId}/permissions`]: {
        item: document, inheritance: { hasUniquePermissions: false, source: null }, warnings: [],
        entries: [{
          principal: { type: 'user', id: 'owner', displayName: 'Test Owner', loginName: null, email: document.knowledgeOwner },
          role: 'Read', roles: ['Read'], grantedVia: 'direct', inheritedFrom: null,
          linkScope: null, linkType: null, expandedMembers: [], accountEnabled: true, accountStatus: 'enabled',
        }],
      },
      '/access/users': { users: [{ userKey: 'owner@contoso.com', displayName: 'Test Owner', userPrincipalName: 'owner@contoso.com', email: 'owner@contoso.com', loginName: 'owner', external: false }] },
      '/access/users/owner@contoso.com/items': {
        items: [{ item: document, role: 'Read', grantedVia: 'direct', via: [], inheritedFrom: null, linkScope: null }],
        page: 1, pageSize: 25, total: 1, totalPages: 1,
      },
      '/analytics/duplicates': { exact: [], near: [], asOfDate: '2026-10-28', libraries: [] },
      '/analytics/expiry': { expired: [{ ...document, expiry }], reviewOverdue: [], asOfDate: '2026-10-28', libraries: [] },
      '/analytics/anomalies': { items: [{ item: document, title: document.title, rank: 1, score: 0.9, isAnomaly: true, topContributions: [] }], libraries: [] },
      '/analytics/exposure': { findings: [{ id: 'exposure-1', type: 'externalDirect', severity: 'medium', subject: document, detail: 'Test-only exposure' }], total: 1, libraries: [] },
      '/agent/prompts': prompts,
      '/agent/messages': { conversationId: 'test', answer: 'Review the test guide.', mode: 'dryRun', intent: 'help', evidence: { items: [{ title: document.title }] }, citations: [{ title: document.title, url: document.webUrl }], warnings: [] },
    };
    let response: unknown;
    if (endpoint === '/notifications/drafts') {
      const body = request.postDataJSON();
      const notification: NotificationItem = {
        id: 'test-notification', status: 'draft', mode: 'dryRun', templateId: body.templateId,
        findingId: 'expired-documents', documentId, documentTitle: document.title,
        documentUrl: document.webUrl, libraryTitle: library.title, ownerUpn: document.knowledgeOwner,
        ownerName: 'Test Owner', to: ['owner@contoso.com'], subject: 'Review test guide', body: 'Test-only draft.',
        reason: null, createdAt: '2026-10-28', approvedAt: null, sentAt: null, delivery: null, error: null,
      };
      outbox.push(notification);
      response = { templateId: body.templateId, findingId: 'expired-documents', mode: 'dryRun', created: [notification], skipped: [] };
    } else if (endpoint === '/notifications') {
      const items = outbox.filter((item) => item.status === url.searchParams.get('status'));
      response = { items, total: items.length, mode: 'dryRun' };
    } else if (endpoint.startsWith('/notifications/test-notification/')) {
      const item = outbox[0];
      item.status = endpoint.endsWith('/approve') ? 'approved' : 'dryRun';
      response = item;
    } else {
      response = responses[decodeURIComponent(endpoint)];
    }
    if (response === undefined) {
      throw new Error(`Unexpected test API request: ${request.method()} ${endpoint}`);
    }
    await route.fulfill({ json: response });
  });
  await signIn(page);
}

test('dashboard finding opens document details, including a direct refresh and category filter', async ({ page }) => {
  await setup(page);
  await page.goto('/dashboard');
  await expect(page.getByTestId('kpi-value')).toHaveText('1');
  await page.getByTestId('finding-toggle').click();
  await page.getByTestId('document-link').click();
  await expect(page.getByTestId('page-document')).toBeVisible();
  const response = await page.reload();
  expect(response?.status()).toBe(200);
  await expect(page.getByTestId('page-document')).toContainText('Test guide');
  await page.goto('/documents');
  await page.locator('ion-segment-button').filter({ hasText: 'Engineering' }).click();
  await expect(page.getByTestId('page-documents')).toContainText('Test guide');
});

test('explorer permissions and access search render records and export CSV', async ({ page }) => {
  await setup(page);
  await page.goto('/explorer');
  await page.getByTestId('library-item').click();
  await page.getByTestId('tree-item').click();
  await expect(page.getByTestId('permission-row')).toContainText('Test Owner');
  await page.goto('/access/by-user');
  await page.getByRole('searchbox').fill('owner');
  await page.getByTestId('user-item').click();
  await expect(page.getByTestId('access-row')).toContainText('Test guide.docx');
  const download = page.waitForEvent('download');
  await page.getByTestId('export-csv').click();
  expect((await download).suggestedFilename()).toBe('access-by-user.csv');
});

test('cleanup drafts persist in the outbox, approve in dry run, and the agent returns citations', async ({ page }) => {
  await setup(page);
  await page.goto('/cleanup');
  await expect(page.getByTestId('state-empty')).toBeVisible();
  for (const segment of ['anomalies', 'exposure', 'expiry']) {
    await page.locator(`ion-segment-button[data-segment="${segment}"]`).click();
    await expect(page.getByTestId('page-cleanup')).toContainText('Test guide.docx');
  }
  await page.getByRole('button', { name: 'Select all', exact: true }).click();
  await page.getByRole('button', { name: 'Draft notifications', exact: true }).click();
  await expect(page.getByTestId('draft-result')).toBeVisible();
  await page.goto('/notifications');
  await page.getByTestId('outbox-item').click();
  await expect(page.getByTestId('preview-subject')).toHaveText('Review test guide');
  await page.getByTestId('approve').click();
  await page.locator('ion-segment-button[data-status="approved"]').click();
  await page.getByTestId('outbox-item').click();
  await expect(page.getByTestId('send')).toBeVisible();
  await page.goto('/agent');
  await page.getByTestId('prompt').first().click();
  await expect(page.getByTestId('agent-answer')).toHaveText('Review the test guide.');
  await expect(page.getByTestId('citations').getByRole('link')).toHaveAttribute('href', document.webUrl!);
});
