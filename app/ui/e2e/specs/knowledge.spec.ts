import { test, expect, Route } from '@playwright/test';
import { configureBrowser, signIn } from '../fixtures/signed-in';
import prompts from '../fixtures/test-only-agent-prompts.json';

const query = 'What is the recommended workaround for the firmware 4.8.2 adaptive polling issue and why?';
const messages = [
  { id: 'm1', author: 'Priya Raman', role: 'Support Engineer', postedAt: '09:02', text: 'Qualification runs keep failing at the polling stage.' },
  { id: 'm2', author: 'Daniel Okafor', role: 'Engineer', postedAt: '09:14', text: 'We confirmed the qualification issue was caused by firmware 4.8.2. The workaround is to disable adaptive polling until 4.8.3 ships.' },
  { id: 'm3', author: 'Marcus Chen', role: 'Test Engineer', postedAt: '09:25', text: 'The lab is closed Friday afternoon.' },
];
const config = {
  enabled: true,
  caller: { upn: 'auditor@contoso.com', name: 'Test Auditor' },
  taxonomy: {
    categories: ['Decision', 'How-To', 'Troubleshooting', 'Other'],
    departments: ['Engineering', 'Support'],
    sensitivities: ['General', 'Confidential'],
  },
  review: { defaultMonths: 6, maxMonths: 36, lowConfidenceThreshold: 0.6 },
  extraction: { provider: 'demo', label: 'Demo extractor', demo: true, maxMessages: 10, maxSourceChars: 12000 },
  publishing: { mode: 'demo', demo: true, siteName: 'Knowledge Hub', libraryName: 'Documents', folder: 'Knowledge Capture', sourceType: 'Teams Collaboration' },
  indexing: { mode: 'demo', scheduleHint: 'Hourly.' },
  demo: { query, conversation: { id: 'demo', title: 'ApexDrive X500 qualification', channel: 'Teams group chat (simulated)', participants: [], keyMessageIds: ['m2'], messages } },
};
const draft = {
  title: 'Firmware 4.8.2 Adaptive Polling Workaround',
  executiveSummary: 'Disable adaptive polling until 4.8.3.',
  category: 'Troubleshooting',
  issueContext: 'Qualification runs failed.',
  rootCause: 'Firmware 4.8.2.',
  decision: '',
  recommendedAction: 'Disable adaptive polling.',
  keyFacts: ['Affected: 4.8.2'],
  department: 'Engineering',
  product: 'ApexDrive X500',
  ownerName: 'Test Auditor',
  ownerUpn: 'auditor@contoso.com',
  ownerMention: '',
  sourceType: 'Teams Collaboration',
  sourceDescription: 'Teams chat',
  sensitivity: 'General',
  reviewDate: '2999-01-01',
  tags: ['firmware'],
  confidence: 0.86,
  status: 'Draft',
  origins: { title: 'ai', executiveSummary: 'ai', issueContext: 'source', rootCause: 'source', decision: 'unknown', recommendedAction: 'source', keyFacts: 'source', category: 'ai', department: 'ai', product: 'source', sensitivity: 'ai', tags: 'ai', owner: 'default', reviewDate: 'default', sourceDescription: 'source' },
};
const published = {
  artifactId: 'KNW-ABCD1234', title: draft.title, fileName: 'Workaround.docx', category: 'Troubleshooting',
  ownerName: 'Test Auditor', ownerUpn: 'auditor@contoso.com', publishedAt: '2026-10-30T12:00:00+00:00',
  reviewDate: '2027-04-30', lifecycleStatus: 'Published', authoritative: true, aiReady: true, aiReadyBlockers: [],
  trustScore: 100, location: { mode: 'demo', siteName: 'Knowledge Hub', libraryName: 'Documents', folder: 'Knowledge Capture', webUrl: null },
  demo: true, appliedFields: {}, skippedFields: [], warnings: [],
  indexing: { stage: 'published', message: 'Demo mode: published.', mode: 'demo', indexer: null, checkedAt: '2026-10-30T12:00:00+00:00', canTrigger: false },
};

test('select, save as knowledge, review, publish and ask AI', async ({ page }) => {
  let publishBody: Record<string, unknown> | null = null;
  let extractBody: { messages: { id: string }[] } | null = null;
  let asked = '';
  await configureBrowser(page, async (route: Route) => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname.replace('/api/v1', '');
    if (endpoint === '/knowledge/config') {
      await route.fulfill({ json: config });
    } else if (endpoint === '/knowledge/extract') {
      extractBody = request.postDataJSON();
      await route.fulfill({ json: { draft, provider: 'demo', providerLabel: 'Demo extractor', demo: true, messageCount: 1, warnings: [] } });
    } else if (endpoint === '/knowledge/publish') {
      publishBody = request.postDataJSON();
      await route.fulfill({ json: published });
    } else if (endpoint.startsWith('/knowledge/artifacts/')) {
      await route.fulfill({ json: { ...published.indexing, stage: 'available', message: 'Available to AI.' } });
    } else if (endpoint === '/agent/prompts') {
      await route.fulfill({ json: prompts });
    } else if (endpoint === '/agent/messages') {
      asked = String(request.postDataJSON().prompt);
      await route.fulfill({ json: { conversationId: 'c', answer: '**Disable adaptive polling.**', mode: 'evidence', intent: 'help', evidence: { items: [] }, citations: [{ title: draft.title, url: null }], warnings: [] } });
    } else {
      await route.fulfill({ json: {} });
    }
  });
  await signIn(page);
  await page.goto('/knowledge');

  await expect(page.getByTestId('knowledge-journey')).toBeVisible();
  await expect(page.getByTestId('knowledge-principle')).toContainText('does not archive');
  await expect(page.getByTestId('save-as-knowledge')).toBeDisabled();
  await page.locator('[data-message-id="m2"]').click();
  await expect(page.getByTestId('selected-count')).toHaveText('1 selected');
  await page.getByTestId('save-as-knowledge').click();

  await expect(page.getByTestId('knowledge-review')).toBeVisible();
  expect(extractBody!.messages.map((message) => message.id)).toEqual(['m2']);
  await expect(page.getByTestId('detected-type')).toHaveText('Troubleshooting');
  await expect(page.getByTestId('detected-title')).toHaveText('Firmware 4.8.2 Adaptive Polling Workaround');
  await expect(page.getByTestId('origin-decision')).toHaveAttribute('data-origin', 'unknown');
  await expect(page.getByTestId('origin-title')).toHaveAttribute('data-origin', 'ai');

  // Nothing is published without the explicit confirmation and a valid review date.
  await page.getByTestId('publish').click();
  await expect(page.getByTestId('error-attestation')).toBeVisible();
  await expect(page.getByTestId('error-reviewDate')).toBeVisible();
  expect(publishBody).toBeNull();

  await page.locator('#kc-reviewDate').fill('2027-04-30');
  await page.locator('#kc-title').fill('Firmware 4.8.2 Polling Workaround (edited)');
  await page.getByTestId('attest').check();
  await page.getByTestId('publish').click();

  await expect(page.getByTestId('knowledge-success')).toBeVisible();
  expect(publishBody).toMatchObject({ title: 'Firmware 4.8.2 Polling Workaround (edited)', attested: true, authoritative: true, reviewDate: '2027-04-30', selectedMessageCount: 1 });
  await expect(page.getByTestId('success-title')).toHaveText('Knowledge preserved');
  await expect(page.getByTestId('demo-note')).toBeVisible();
  await expect(page.getByTestId('indexing-tracker')).toBeVisible();
  await expect(page.getByTestId('demo-query')).toHaveText(query);

  await page.getByTestId('ask-ai').click();
  await expect(page).toHaveURL(/\/agent/);
  await expect(page.getByTestId('agent-answer')).toContainText('Disable adaptive polling.');
  expect(asked).toBe(query);
});

test('an extraction failure offers a retry and a blank draft, and a publish failure keeps the form', async ({ page }) => {
  let publishFails = true;
  await configureBrowser(page, async (route: Route) => {
    const endpoint = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (endpoint === '/knowledge/config') {
      await route.fulfill({ json: config });
    } else if (endpoint === '/knowledge/extract') {
      await route.fulfill({ status: 502, json: { error: { code: 'extraction_failed', message: 'Microsoft Foundry: knowledge extraction failed.' } } });
    } else if (endpoint === '/knowledge/draft/blank') {
      await route.fulfill({ json: { ...draft, title: '', executiveSummary: '', rootCause: '', recommendedAction: '', origins: {} } });
    } else if (endpoint === '/knowledge/publish') {
      if (publishFails) {
        await route.fulfill({ status: 502, json: { error: { code: 'sharepoint_write_denied', message: 'SharePoint: write access was denied.' } } });
      } else {
        await route.fulfill({ json: published });
      }
    } else {
      await route.fulfill({ json: {} });
    }
  });
  await signIn(page);
  await page.goto('/knowledge');
  await page.locator('[data-message-id="m2"]').click();
  await page.getByTestId('save-as-knowledge').click();
  await expect(page.getByTestId('knowledge-extract-failed')).toContainText('knowledge extraction failed');
  await page.getByTestId('extract-manual').click();

  await expect(page.getByTestId('knowledge-review')).toBeVisible();
  await page.locator('#kc-title').fill('Manual knowledge title');
  await page.locator('#kc-executiveSummary').fill('Written by hand.');
  await page.locator('#kc-recommendedAction').fill('Do the thing.');
  await page.locator('#kc-reviewDate').fill('2027-04-30');
  await page.getByTestId('attest').check();
  await page.getByTestId('publish').click();

  await expect(page.getByTestId('publish-error')).toContainText('write access was denied');
  await expect(page.locator('#kc-title')).toHaveValue('Manual knowledge title');
  publishFails = false;
  await page.getByTestId('publish').click();
  await expect(page.getByTestId('knowledge-success')).toBeVisible();
});
