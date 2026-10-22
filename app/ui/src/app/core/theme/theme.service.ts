import { DOCUMENT } from '@angular/common';
import { Injectable, inject } from '@angular/core';
import { ConfigService } from '../config/config.service';
import { ThemeConfig } from '../config/config.models';
import { hexToRgb, mixHex, relativeLuminance } from './color';

const SHADE_WEIGHT = 0.12;
const TINT_WEIGHT = 0.12;

/**
 * Writes layout.json and theme.json into CSS custom properties on <html> at startup.
 * Stylesheets reference only var(--...) names, so no colour or size is hardcoded in SCSS.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly config = inject(ConfigService);
  private readonly document = inject(DOCUMENT);

  apply(): void {
    const root = this.document.documentElement;
    const set = (name: string, value: string): void => root.style.setProperty(name, value);
    const { layout, theme, strings } = this.config.current;

    for (const [key, value] of Object.entries(layout.spacingPx)) {
      set(`--space-${key}`, `${value}px`);
    }
    set('--radius', `${layout.radiusPx}px`);
    set('--fab-offset', `${layout.fabOffsetPx}px`);
    set('--layout-header-height', `${layout.headerHeightPx}px`);
    set('--layout-tab-bar-height', `${layout.tabBarHeightPx}px`);
    set('--layout-sidebar-width', `${layout.sidebarWidthPx}px`);
    set('--layout-max-content-width', `${layout.maxContentWidthPx}px`);
    set('--pane-list-width', `${layout.paneWidths.listPercent}%`);
    set('--pane-detail-width', `${layout.paneWidths.detailPercent}%`);

    for (const [name, color] of Object.entries(theme.brandColors)) {
      set(`--brand-${name}`, color);
    }
    for (const [name, color] of Object.entries(theme.surfaces)) {
      set(`--surface-${toKebab(name)}`, color);
    }
    set('--contrast-light', theme.contrast.light);
    set('--contrast-dark', theme.contrast.dark);

    applyIonicColors(set, theme);

    set('--ion-background-color', theme.surfaces['page']);
    set('--ion-text-color', theme.surfaces['text']);
    set('--ion-toolbar-background', theme.surfaces['header']);
    set('--ion-toolbar-color', theme.surfaces['text']);
    set('--ion-border-color', theme.surfaces['border']);
    set('--ion-card-background', theme.surfaces['card']);
    set('--ion-card-color', theme.surfaces['text']);

    this.document.title = strings.appName;
    root.lang = strings.lang;
  }
}

function applyIonicColors(set: (name: string, value: string) => void, theme: ThemeConfig): void {
  const light = theme.contrast.light;
  const dark = theme.contrast.dark;
  for (const [name, base] of Object.entries(theme.ionicColors)) {
    const contrast = relativeLuminance(base) > 0.5 ? dark : light;
    const rgb = hexToRgb(base).join(', ');
    const contrastRgb = hexToRgb(contrast).join(', ');
    set(`--ion-color-${name}`, base);
    set(`--ion-color-${name}-rgb`, rgb);
    set(`--ion-color-${name}-contrast`, contrast);
    set(`--ion-color-${name}-contrast-rgb`, contrastRgb);
    set(`--ion-color-${name}-shade`, mixHex(base, dark, SHADE_WEIGHT));
    set(`--ion-color-${name}-tint`, mixHex(base, light, TINT_WEIGHT));
  }
}

function toKebab(value: string): string {
  return value.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
}
