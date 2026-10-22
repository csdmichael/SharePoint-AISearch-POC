import { DOCUMENT } from '@angular/common';
import { DestroyRef, Injectable, computed, effect, inject, signal } from '@angular/core';
import { ConfigService } from '../config/config.service';
import { LayoutName } from '../config/config.models';

/**
 * Classifies the viewport with matchMedia using tabletMinPx and desktopMinPx from layout.json.
 * Sets data-layout on <html> and --card-columns so SCSS never needs a literal breakpoint.
 */
@Injectable({ providedIn: 'root' })
export class LayoutService {
  private readonly config = inject(ConfigService);
  private readonly document = inject(DOCUMENT);

  private readonly tabletMatch = signal(false);
  private readonly desktopMatch = signal(false);

  readonly layout = computed<LayoutName>(() => {
    if (this.desktopMatch()) {
      return 'desktop';
    }
    return this.tabletMatch() ? 'tablet' : 'mobile';
  });
  readonly isMobile = computed(() => this.layout() === 'mobile');
  readonly isTablet = computed(() => this.layout() === 'tablet');
  readonly isDesktop = computed(() => this.layout() === 'desktop');
  readonly cardColumns = computed(() => this.config.layout.cardColumns[this.layout()]);

  constructor() {
    const view = this.document.defaultView;
    if (view && typeof view.matchMedia === 'function') {
      const { tabletMinPx, desktopMinPx } = this.config.layout.breakpoints;
      const tablet = view.matchMedia(`(min-width: ${tabletMinPx}px)`);
      const desktop = view.matchMedia(`(min-width: ${desktopMinPx}px)`);
      const update = (): void => {
        this.tabletMatch.set(tablet.matches);
        this.desktopMatch.set(desktop.matches);
      };
      update();
      tablet.addEventListener('change', update);
      desktop.addEventListener('change', update);
      inject(DestroyRef).onDestroy(() => {
        tablet.removeEventListener('change', update);
        desktop.removeEventListener('change', update);
      });
    }

    effect(() => {
      const root = this.document.documentElement;
      const layout = this.layout();
      root.setAttribute('data-layout', layout);
      root.style.setProperty('--card-columns', String(this.cardColumns()));
      const { fabOffsetPx, tabBarHeightPx } = this.config.layout;
      const bottom = layout === 'mobile' ? tabBarHeightPx + fabOffsetPx : fabOffsetPx;
      root.style.setProperty('--fab-bottom', `${bottom}px`);
    });
  }
}
