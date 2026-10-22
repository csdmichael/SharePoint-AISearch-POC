import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { IonButton, IonIcon, MenuController } from '@ionic/angular';
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
    <header class="app-header" data-testid="app-header">
      <app-microsoft-logo />
      <span class="app-header__title" data-testid="app-title">{{ appName }}</span>
      @if (modeBadge(); as badge) {
        <app-badge data-testid="mode-badge" [text]="badge.text" [color]="badge.color" />
      }
      <span class="app-header__spacer"></span>
      @if (session.auth.signedIn()) {
        <span class="app-header__user" data-testid="signed-in-user">{{ signedInText() }}</span>
      }
      @if (!layout.isDesktop()) {
        <ion-button fill="clear" data-testid="menu-button" [attr.aria-label]="menuLabel" [attr.title]="menuLabel" (click)="openMenu()">
          <ion-icon slot="icon-only" [name]="icons.menu" aria-hidden="true" />
        </ion-button>
      }
      @if (session.auth.signedIn()) {
        <ion-button fill="outline" size="small" data-testid="sign-out-button" (click)="signOut()">
          <ion-icon slot="start" [name]="icons.signOut" aria-hidden="true" />
          {{ 'buttons.signOut' | t }}
        </ion-button>
      } @else {
        <ion-button fill="solid" size="small" data-testid="sign-in-button" [disabled]="!session.auth.configured" (click)="signIn()">
          <ion-icon slot="start" [name]="icons.signIn" aria-hidden="true" />
          {{ 'buttons.signIn' | t }}
        </ion-button>
      }
    </header>
  `,
  styleUrl: './app-header.component.scss',
})
export class AppHeaderComponent {
  private readonly config = inject(ConfigService);
  private readonly i18n = inject(I18nService);
  private readonly display = inject(DisplayService);
  private readonly menu = inject(MenuController);
  readonly layout = inject(LayoutService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;
  readonly appName = this.config.strings.appName;
  readonly menuLabel = this.i18n.text('header.menuButtonLabel');

  readonly modeBadge = computed(() => {
    const key = this.session.apiStatus() === 'checking' ? 'checking' : this.session.apiStatus() === 'unreachable' ? 'offline' : this.session.mode();
    if (!key) {
      return null;
    }
    return { text: this.i18n.text(`modeBadges.${key}`), color: this.display.statusColor(key) };
  });

  readonly signedInText = computed(() => this.i18n.text('header.signedInAs', { name: this.session.auth.displayName() }));

  openMenu(): void {
    void this.menu.open(this.config.layout.overlayMenuId);
  }

  signIn(): void {
    void this.session.signIn();
  }

  signOut(): void {
    void this.session.signOut();
  }
}
