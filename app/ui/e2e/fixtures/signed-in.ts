import { expect, Page, Route } from '@playwright/test';
import type * as Msal from '@azure/msal-browser';
import path from 'node:path';
import appConfig from '../../src/assets/config/app.config.json';
import serverConfig from '../config/e2e-server.json';
import testAuth from '../config/test-auth.json';
import health from './test-only-health-live.json';

declare global {
  interface Window {
    msal: typeof Msal;
  }
}

export const documentId = '00000000-0000-4000-8000-000000000004.1';
export const routes = [
  ['/dashboard', 'Dashboard'],
  ['/explorer', 'Explorer'],
  ['/documents', 'Documents'],
  [`/documents/${documentId}`, 'Document details'],
  ['/access/by-user', 'Access by user'],
  ['/cleanup', 'Cleanup'],
  ['/notifications', 'Notifications'],
  ['/agent', 'Site Assistant'],
] as const;

export async function configureBrowser(page: Page, api: (route: Route) => Promise<void>): Promise<void> {
  await page.route('**/assets/config/app.config.json', (route) => route.fulfill({
    json: {
      ...appConfig,
      requestTimeoutMs: 1000,
      auth: {
        ...testAuth.auth,
        redirectUri: serverConfig.url,
        postLogoutRedirectUri: serverConfig.url,
        cacheLocation: 'sessionStorage',
      },
    },
  }));
  await page.route('**/*microsoftonline.com/**', (route) => route.abort());
  await page.route('**/api/v1/**', async (route) => {
    if (new URL(route.request().url()).pathname.endsWith('/health')) {
      await route.fulfill({ json: health });
    } else {
      await api(route);
    }
  });
}

/** Populate MSAL through its public API; no production auth bypass or real credentials. */
export async function signIn(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.getByTestId('state-sign-in')).toBeVisible();
  await page.addScriptTag({ path: path.resolve('node_modules', '@azure', 'msal-browser', 'lib', 'msal-browser.min.js') });
  await page.evaluate(async ({ auth, url }) => {
    const tenantId = auth.authority.split('/').pop()!;
    const authority = auth.authority;
    const client = await window.msal.createStandardPublicClientApplication({
      auth: {
        clientId: auth.clientId,
        authority,
        redirectUri: url,
        cloudDiscoveryMetadata: JSON.stringify({
          tenant_discovery_endpoint: `${authority}/v2.0/.well-known/openid-configuration`,
          metadata: [{
            preferred_network: 'login.microsoftonline.com',
            preferred_cache: 'login.microsoftonline.com',
            aliases: ['login.microsoftonline.com'],
          }],
        }),
        authorityMetadata: JSON.stringify({
          issuer: `${authority}/v2.0`,
          authorization_endpoint: `${authority}/oauth2/v2.0/authorize`,
          token_endpoint: `${authority}/oauth2/v2.0/token`,
          end_session_endpoint: `${authority}/oauth2/v2.0/logout`,
          jwks_uri: `${authority}/discovery/v2.0/keys`,
        }),
      },
      cache: { cacheLocation: 'sessionStorage' },
    });
    const claims = {
      aud: auth.clientId, iss: `${authority}/v2.0`, tid: tenantId, oid: 'test-auditor',
      sub: 'test-auditor', name: 'Test Auditor', preferred_username: 'auditor@contoso.com',
      iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 3600,
    };
    const account: Msal.AccountInfo = {
      homeAccountId: `test-auditor.${tenantId}`, localAccountId: 'test-auditor',
      environment: 'login.microsoftonline.com', tenantId, username: claims.preferred_username,
      name: claims.name, idTokenClaims: claims,
    };
    const idToken = `${btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))}.${btoa(JSON.stringify(claims))}.test-only`;
    await client.hydrateCache({
      authority, uniqueId: 'test-auditor', tenantId, scopes: auth.apiScopes, account,
      idToken, idTokenClaims: claims, accessToken: 'test-only-access-token',
      fromCache: true, expiresOn: new Date(Date.now() + 3600000), tokenType: 'Bearer',
      correlationId: 'test-only',
    }, { scopes: auth.apiScopes });
    client.setActiveAccount(account);
  }, { auth: testAuth.auth, url: serverConfig.url });
}
