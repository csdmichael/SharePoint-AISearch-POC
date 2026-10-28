import { Injectable, inject } from '@angular/core';
import { ConfigService } from '../../core/config/config.service';
import { I18nService, lookupString } from '../../core/i18n/i18n.service';

export type ValueGroup =
  | 'grantedVia'
  | 'principalType'
  | 'kind'
  | 'severity'
  | 'lifecycleStatus'
  | 'dataQualityStatus'
  | 'conflictStatus';

/** Labels and colours for values returned by the API. Unknown values are shown as received. */
@Injectable({ providedIn: 'root' })
export class DisplayService {
  private readonly config = inject(ConfigService);
  private readonly i18n = inject(I18nService);

  /** Translated label for a known API value, otherwise the raw value, otherwise the not-available text. */
  label(group: ValueGroup, value: string | null | undefined): string {
    if (value === null || value === undefined || value.trim() === '') {
      return this.i18n.text('states.notAvailable');
    }
    return lookupString(this.config.strings, `values.${group}.${value}`) ?? value;
  }

  statusColor(status: string | null | undefined): string {
    const colors = this.config.theme.statusColors;
    return (status ? colors[status] : undefined) ?? colors['default'];
  }

  severityColor(severity: string | null | undefined): string {
    const colors = this.config.theme.severityColors;
    return (severity ? colors[severity] : undefined) ?? colors['medium'] ?? this.config.theme.statusColors['default'];
  }

  /** Colour of the first band whose minScore the score reaches (bands are checked from highest to lowest). */
  trustColor(score: number): string {
    const bands = [...this.config.theme.trustScoreColors].sort((a, b) => b.minScore - a.minScore);
    const band = bands.find((entry) => score >= entry.minScore) ?? bands[bands.length - 1];
    return band.color;
  }

  notAvailable(): string {
    return this.i18n.text('states.notAvailable');
  }

  /** Up to two initials for an avatar. Email addresses use their local part. */
  initials(name: string): string {
    const local = name.includes('@') ? name.split('@')[0] : name;
    const parts = local.split(/[\s._-]+/).filter(Boolean);
    if (parts.length === 0) {
      return '';
    }
    const first = parts[0].charAt(0);
    const last = parts.length > 1 ? parts[parts.length - 1].charAt(0) : '';
    return `${first}${last}`.toUpperCase();
  }
}
