import { ChangeDetectionStrategy, Component, computed, effect, inject } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { IonButton, IonIcon, MenuController } from '@ionic/angular';
import { ApiService } from '../../../core/api/api.service';
import { SiteDescriptor } from '../../../core/api/models/api.models';
import { ConfigService } from '../../../core/config/config.service';
import { I18nService } from '../../../core/i18n/i18n.service';
import { LayoutService } from '../../../core/layout/layout.service';
import { SessionService } from '../../../core/session/session.service';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { DisplayService } from '../../util/display.service';
import { BadgeComponent } from '../badge/badge.component';
import { MicrosoftLogoComponent } from '../microsoft-logo/microsoft-logo.component';

/** Top bar on every page: Microsoft logo, app title, mode badge, menu (tablet and mobile), and sign-in or sign-out. */
@Component({
  selector: 'app-header',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonButton, IonIcon, MicrosoftLogoComponent, BadgeComponent, TranslatePipe],
  template: `
    <header class="app-header" data-testid="app-header" [class.app-header--compact]="layout.isMobile()" [class.app-header--hide-name]="!layout.isDesktop()">
      <app-microsoft-logo [compact]="layout.isMobile()" />
      <span class="app-header__divider" aria-hidden="true"></span>
      <span class="app-header__title" data-testid="app-title">{{ appName }}</span>
      @if (modeBadge(); as badge) {
        <app-badge data-testid="mode-badge" [text]="badge.text" [color]="badge.color" />
      }
      <span class="app-header__spacer"></span>
      @if (session.gate() === 'ready' && siteOptions().length > 0) {
        <label class="app-header__site">
          <span class="app-header__site-label">{{ siteLabel }}</span>
          <select class="app-header__site-select" [value]="selectedSiteId() ?? ''" (change)="changeSite($event)">
            @for (site of siteOptions(); track site.siteId) {
              <option [value]="site.siteId">{{ site.displayName }}</option>
            }
          </select>
        </label>
      }
      @if (session.auth.signedIn()) {
        <span class="app-header__user" data-testid="signed-in-user">
          <span class="app-header__avatar" role="img" [attr.aria-label]="signedInText()" [attr.title]="signedInText()">{{ initials() }}</span>
          <span class="app-header__name">{{ signedInText() }}</span>
        </span>
      }
      @if (!layout.isDesktop()) {
        <ion-button class="app-header__icon-button" fill="clear" data-testid="menu-button" [attr.aria-label]="menuLabel" [attr.title]="menuLabel" (click)="openMenu()">
          <ion-icon slot="icon-only" [name]="icons.menu" aria-hidden="true" />
        </ion-button>
      }
      @if (session.auth.signedIn()) {
        <ion-button class="app-header__action" fill="outline" size="small" data-testid="sign-out-button" [attr.aria-label]="signOutLabel" [attr.title]="signOutLabel" (click)="signOut()">
          @if (layout.isMobile()) {
            <ion-icon slot="icon-only" [name]="icons.signOut" aria-hidden="true" />
          } @else {
            <ion-icon slot="start" [name]="icons.signOut" aria-hidden="true" />
            {{ 'buttons.signOut' | t }}
          }
        </ion-button>
      } @else {
        <ion-button class="app-header__action" fill="solid" size="small" data-testid="sign-in-button" [disabled]="!session.auth.configured" [attr.aria-label]="signInLabel" [attr.title]="signInLabel" (click)="signIn()">
          @if (layout.isMobile()) {
            <ion-icon slot="icon-only" [name]="icons.signIn" aria-hidden="true" />
          } @else {
            <ion-icon slot="start" [name]="icons.signIn" aria-hidden="true" />
            {{ 'buttons.signIn' | t }}
          }
        </ion-button>
      }
    </header>
  `,
  styleUrl: './app-header.component.scss',
})
export class AppHeaderComponent {
  private readonly config = inject(ConfigService);
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly display = inject(DisplayService);
  private readonly menu = inject(MenuController);
  readonly layout = inject(LayoutService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;
  readonly appName = this.config.strings.appName;
  readonly menuLabel = this.i18n.text('header.menuButtonLabel');
  readonly siteLabel = this.i18n.text('header.siteLabel');

  readonly modeBadge = computed(() => {
    const key = this.session.apiStatus() === 'checking' ? 'checking' : this.session.apiStatus() === 'unreachable' ? 'offline' : this.session.mode();
    if (!key) {
      return null;
    }
    return { text: this.i18n.text(`modeBadges.${key}`), color: this.display.statusColor(key) };
  });

  readonly signedInText = computed(() => this.i18n.text('header.signedInAs', { name: this.session.auth.displayName() }));
  readonly initials = computed(() => this.display.initials(this.session.auth.displayName()));
  readonly signInLabel = this.i18n.text('buttons.signIn');
  readonly signOutLabel = this.i18n.text('buttons.signOut');
  readonly siteInfo = rxResource({
    params: () => (this.session.gate() === 'ready' ? this.api.siteContext() ?? '__default__' : undefined),
    stream: () => this.api.siteInfo(),
  });
  readonly siteOptions = computed<SiteDescriptor[]>(() => this.siteInfo.hasValue() ? this.siteInfo.value().availableSites : []);
  readonly selectedSiteId = computed(() => this.api.siteContext() ?? (this.siteInfo.hasValue() ? this.siteInfo.value().selectedSite.siteId : null));

  constructor() {
    effect(() => {
      if (!this.siteInfo.hasValue()) {
        return;
      }
      const available = this.siteInfo.value().availableSites;
      if (available.length === 0) {
        return;
      }
      const current = this.api.siteContext();
      if (current && available.some((site) => site.siteId === current)) {
        return;
      }
      this.api.setSiteContext(this.siteInfo.value().selectedSite.siteId);
    });
  }

  openMenu(): void {
    void this.menu.open(this.config.layout.overlayMenuId);
  }

  signIn(): void {
    void this.session.signIn();
  }

  signOut(): void {
    void this.session.signOut();
  }

  changeSite(event: Event): void {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) {
      return;
    }
    this.api.setSiteContext(target.value);
  }
}
