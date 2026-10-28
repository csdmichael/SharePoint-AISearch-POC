import { test, expect } from '@playwright/test';
import { configureBrowser, routes } from '../fixtures/signed-in';
import agentConfig from '../../src/assets/config/agent.json';

test('every page and composite document deep link renders the sign-in state', async ({ page }) => {
  await configureBrowser(page, (route) => route.fulfill({ status: 401, json: { error: { code: 'unauthorized' } } }));
  for (const [url] of routes) {
    const response = await page.goto(url);
    expect(response?.status(), url).toBe(200);
    await expect(page.getByTestId('state-sign-in').first(), url).toBeVisible();
    await expect(page.getByTestId('app-header')).toBeVisible();
    if (!agentConfig.fab.hideOnRoutes.includes(url)) {
      await expect(page.getByTestId('agent-fab')).toBeVisible();
    }
  }
  const asset = await page.request.get('/missing-bundle.js');
  expect(asset.status()).toBe(404);
  expect(asset.headers()['content-type']).not.toContain('text/html');
});
