import { Injectable, inject } from '@angular/core';
import { ConfigService } from '../config/config.service';
import { StringTable } from '../config/config.models';

export type TextParams = Record<string, string | number>;

/** Resolves a dotted key such as "states.apiUnreachable.title" against the strings table. */
export function lookupString(table: StringTable, dottedKey: string): string | null {
  let node: string | StringTable | undefined = table;
  for (const part of dottedKey.split('.')) {
    if (typeof node !== 'object' || node === null) {
      return null;
    }
    node = node[part];
  }
  return typeof node === 'string' ? node : null;
}

/** Replaces {name} tokens. Unknown tokens are left visible so a missing parameter is obvious. */
export function interpolate(template: string, params: TextParams | undefined): string {
  if (!params) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (token: string, name: string) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : token,
  );
}

@Injectable({ providedIn: 'root' })
export class I18nService {
  private readonly config = inject(ConfigService);

  get lang(): string {
    return this.config.strings.lang;
  }

  /** Returns the configured text. A missing key is logged and shown as the key itself. */
  text(key: string, params?: TextParams): string {
    const value = lookupString(this.config.strings, key);
    if (value === null) {
      console.error(`Missing string key: ${key}`);
      return key;
    }
    return interpolate(value, params);
  }

  number(value: number): string {
    return new Intl.NumberFormat(this.lang).format(value);
  }

  date(value: string | null | undefined): string {
    if (!value) {
      return this.text('states.notAvailable');
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return new Intl.DateTimeFormat(this.lang, { dateStyle: 'medium' }).format(parsed);
  }
}
