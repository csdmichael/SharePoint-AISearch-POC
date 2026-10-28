import { test, expect } from '@playwright/test';
import { configureBrowser, documentId, routes, signIn } from '../fixtures/signed-in';

test('all data pages leave loading, display API failures, and retry', async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on('pageerror', (error) => consoleErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && message.text().includes('Resource is currently in an error state')) {
      consoleErrors.push(message.text());
    }
  });

  let status = 502;
  await configureBrowser(page, (route) => route.fulfill({
    status,
    json: { error: { code: status === 401 ? 'unauthorized' : 'upstream_forbidden', message: 'Test-only failure' } },
  }));
  await signIn(page);
  for (const [url] of routes) {
    await page.goto(url);
    if (url === '/access/by-user') {
      await page.getByRole('searchbox').fill('auditor');
    }
    const error = page.getByTestId('state-view').filter({ has: page.getByTestId('state-retry') }).first();
    await expect(error, url).toHaveAttribute('data-state', 'error');
    await expect(error).toHaveAttribute('data-error', 'server');
    const retried = page.waitForRequest((request) =>
      request.url().includes('/api/v1/') && !request.url().endsWith('/health'));
    await error.getByTestId('state-retry').click();
    await retried;
    await expect(error).toHaveAttribute('data-state', 'error');
    await expect(page.locator('[data-state="loading"]')).toHaveCount(0);
  }
  expect(consoleErrors).toEqual([]);
  status = 401;
  await page.goto(`/documents/${documentId}`);
  await expect(page.getByTestId('state-sign-in')).toBeVisible();
  await expect(page.locator('[data-state="loading"]')).toHaveCount(0);
});

test('a timed-out document request stops loading and recovers on retry', async ({ page }) => {
  let slow = true;
  await configureBrowser(page, async (route) => {
    if (slow) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    await route.fulfill({ json: {
      items: [], page: 1, total: 0, totalPages: 1, pageSize: 25, knowledgeCategories: [],
    } });
  });
  await signIn(page);
  await page.goto('/documents');
  await expect(page.getByTestId('state-view')).toHaveAttribute('data-gate', 'apiUnreachable');
  await expect(page.locator('[data-state="loading"]')).toHaveCount(0);
  slow = false;
  await page.getByTestId('state-retry').click();
  await expect(page.getByTestId('state-empty')).toBeVisible();
});
