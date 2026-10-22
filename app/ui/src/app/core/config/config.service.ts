import { HttpBackend, HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AgentConfig, AppConfig, ConfigBundle, LayoutConfig, NavigationConfig, PagesConfig, RawConfigFiles, ThemeConfig } from './config.models';
import { ConfigValidationError, validateConfigBundle } from './config.validation';

const CONFIG_DIRECTORY = 'assets/config/';

/**
 * Loads and holds the startup configuration. Runs from APP_INITIALIZER, before any
 * component reads a value, and fails fast when a file is missing or a key is invalid.
 */
@Injectable({ providedIn: 'root' })
export class ConfigService {
  private readonly backend = inject(HttpBackend);
  private bundle: ConfigBundle | null = null;

  get isLoaded(): boolean {
    return this.bundle !== null;
  }

  get current(): ConfigBundle {
    if (!this.bundle) {
      throw new Error('Configuration is not loaded. It is loaded during application startup.');
    }
    return this.bundle;
  }

  get app(): AppConfig {
    return this.current.app;
  }

  get layout(): LayoutConfig {
    return this.current.layout;
  }

  get navigation(): NavigationConfig {
    return this.current.navigation;
  }

  get agent(): AgentConfig {
    return this.current.agent;
  }

  get strings(): ConfigBundle['strings'] {
    return this.current.strings;
  }

  get theme(): ThemeConfig {
    return this.current.theme;
  }

  get pages(): PagesConfig {
    return this.current.pages;
  }

  get logoSvg(): string {
    return this.current.logoSvg;
  }

  async load(): Promise<void> {
    // HttpBackend skips interceptors, so the auth layer cannot run before configuration exists.
    const http = new HttpClient(this.backend);
    const fetchJson = (file: string): Promise<unknown> => fetchOrFail(http, file);

    const [app, layout, navigation, agent, strings, theme, pages] = await Promise.all([
      fetchJson('app.config.json'),
      fetchJson('layout.json'),
      fetchJson('navigation.json'),
      fetchJson('agent.json'),
      fetchJson('strings.json'),
      fetchJson('theme.json'),
      fetchJson('pages.json'),
    ]);

    const logoPath = typeof (theme as { logoPath?: unknown } | null)?.logoPath === 'string' ? (theme as { logoPath: string }).logoPath : '';
    const logoSvg = logoPath ? await fetchText(http, logoPath) : '';

    this.install({ app, layout, navigation, agent, strings, theme, pages }, logoSvg);
  }

  /** Validates raw configuration and makes it the active bundle. Used at startup and by tests. */
  install(raw: RawConfigFiles, logoSvg: string): void {
    const logoPath = typeof (raw.theme as { logoPath?: unknown } | null)?.logoPath === 'string' ? String((raw.theme as { logoPath: unknown }).logoPath) : '';
    this.bundle = validateConfigBundle(raw, logoSvg, logoPath);
  }
}

async function fetchOrFail(http: HttpClient, file: string): Promise<unknown> {
  try {
    return await firstValueFrom(http.get<unknown>(CONFIG_DIRECTORY + file, { responseType: 'json' }));
  } catch (error) {
    throw new ConfigValidationError([`${file}: could not be loaded (${describeHttpError(error)})`]);
  }
}

async function fetchText(http: HttpClient, path: string): Promise<string> {
  try {
    return await firstValueFrom(http.get(path, { responseType: 'text' }));
  } catch (error) {
    throw new ConfigValidationError([`${path}: brand logo could not be loaded (${describeHttpError(error)})`]);
  }
}

function describeHttpError(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    return error.status === 0 ? 'network error' : `HTTP ${error.status}`;
  }
  return error instanceof Error ? error.message : 'unknown error';
}
