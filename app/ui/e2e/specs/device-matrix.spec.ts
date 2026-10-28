import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import devicesConfig from '../config/devices.json';
import serverConfig from '../config/e2e-server.json';
import healthFixture from '../fixtures/test-only-health-live.json';
import promptsFixture from '../fixtures/test-only-agent-prompts.json';

test.describe('Responsive Device Matrix', () => {
  test('header logo, agent FAB, and navigation match device class', async ({ page }, testInfo) => {
    const device = devicesConfig.devices.find((d) => d.name === testInfo.project.name);
    if (!device) {
      throw new Error(`Device profile "${testInfo.project.name}" not found in devices.json.`);
    }

    // Intercept API calls using test-only synthetic fixtures
    await page.route('**/api/v1/health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(healthFixture),
      });
    });

    await page.route('**/api/v1/agent/prompts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(promptsFixture),
      });
    });

    // Catch-all mock for other endpoints to prevent network aborts
    await page.route('**/api/v1/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ testOnly: true, items: [] }),
      });
    });

    // Guard: abort any external Entra authentication calls
    await page.route('**/*microsoftonline.com/**', async (route) => {
      await route.abort();
    });

    await page.goto('/');

    // 1. Verify Microsoft logo in the app header
    const header = page.getByTestId('app-header');
    await expect(header).toBeVisible();
    const logo = page.getByTestId('ms-logo');
    await expect(logo).toBeVisible();

    // 2. Verify Foundry agent FAB is visible
    const fab = page.getByTestId('agent-fab');
    await expect(fab).toBeVisible();

    // 2b. Verify footer is visible with author, LinkedIn, and GitHub links
    const footer = page.getByTestId('app-footer');
    await expect(footer).toBeVisible();
    await expect(footer).toContainText('Michael Yaacoub');
    await expect(footer.getByRole('link', { name: 'LinkedIn' })).toHaveAttribute(
      'href',
      'https://www.linkedin.com/in/michael-yaacoub-7a46436/',
    );
    await expect(footer.getByRole('link', { name: 'GitHub' })).toHaveAttribute(
      'href',
      'https://github.com/csdmichael/SharePoint-AISearch-POC',
    );

    // 3. Verify navigation matches device class
    if (device.deviceClass === 'phone') {
      // Phone: bottom tab bar is visible
      await expect(page.getByTestId('mobile-tab-bar')).toBeVisible();
      await expect(page.getByTestId('sidebar')).toHaveCount(0);
    } else if (device.deviceClass === 'web' || device.deviceClass === 'desktop') {
      // Desktop and web: persistent sidebar is visible
      await expect(page.getByTestId('sidebar')).toBeVisible();
      await expect(page.getByTestId('mobile-tab-bar')).toHaveCount(0);
    } else if (device.deviceClass === 'tablet') {
      // Tablet: navigation via menu button for overlay menu, or sidebar if desktop layout
      const sidebar = page.getByTestId('sidebar');
      const hasSidebar = (await sidebar.count()) > 0 && (await sidebar.isVisible());
      if (hasSidebar) {
        await expect(sidebar).toBeVisible();
      } else {
        await expect(page.getByTestId('menu-button')).toBeVisible();
      }
      await expect(page.getByTestId('mobile-tab-bar')).toHaveCount(0);
    }

    // 4. Save a screenshot per device to test-results/screenshots/
    const screenshotDir = path.resolve(serverConfig.screenshotDir);
    fs.mkdirSync(screenshotDir, { recursive: true });
    const screenshotPath = path.join(screenshotDir, `${device.name}.png`);
    await page.screenshot({ path: screenshotPath });
  });
});
