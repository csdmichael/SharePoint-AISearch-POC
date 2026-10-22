import { Injectable, computed, inject, signal } from '@angular/core';
import {
  AccountInfo,
  InteractionRequiredAuthError,
  IPublicClientApplication,
  createStandardPublicClientApplication,
} from '@azure/msal-browser';
import { ConfigService } from '../config/config.service';

/** MSAL (Microsoft Entra) sign-in for the SPA registration in app.config.json. Nothing is bypassed when unconfigured. */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly config = inject(ConfigService);
  private msal: IPublicClientApplication | null = null;

  readonly account = signal<AccountInfo | null>(null);
  readonly initFailed = signal(false);
  readonly signedIn = computed(() => this.account() !== null);
  readonly displayName = computed(() => {
    const account = this.account();
    return account ? account.name ?? account.username : '';
  });

  /** False until the SPA registration exists (auth.clientId is empty in app.config.json). */
  get configured(): boolean {
    return this.config.app.auth.clientId.length > 0;
  }

  async initialize(): Promise<void> {
    if (!this.configured) {
      return;
    }
    const auth = this.config.app.auth;
    try {
      const msal = await createStandardPublicClientApplication({
        auth: {
          clientId: auth.clientId,
          authority: auth.authority,
          redirectUri: auth.redirectUri,
          postLogoutRedirectUri: auth.postLogoutRedirectUri,
        },
        cache: { cacheLocation: auth.cacheLocation },
      });
      const redirect = await msal.handleRedirectPromise();
      const account = redirect?.account ?? msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
      if (account) {
        msal.setActiveAccount(account);
      }
      this.msal = msal;
      this.account.set(account);
    } catch (error) {
      this.initFailed.set(true);
      console.error('Sign-in could not be initialized.', error);
    }
  }

  async signIn(): Promise<void> {
    if (!this.msal) {
      return;
    }
    await this.msal.loginRedirect({ scopes: this.config.app.auth.apiScopes });
  }

  async signOut(): Promise<void> {
    if (!this.msal) {
      return;
    }
    const account = this.account();
    await this.msal.logoutRedirect({ account: account ?? undefined });
  }

  /** Silent token for the API scopes. Returns null when the user must sign in again. */
  async acquireToken(): Promise<string | null> {
    const account = this.account();
    if (!this.msal || !account) {
      return null;
    }
    try {
      const result = await this.msal.acquireTokenSilent({ account, scopes: this.config.app.auth.apiScopes });
      return result.accessToken;
    } catch (error) {
      if (!(error instanceof InteractionRequiredAuthError)) {
        console.error('Token acquisition failed.', error);
      }
      return null;
    }
  }
}
