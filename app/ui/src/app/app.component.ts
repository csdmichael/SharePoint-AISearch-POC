import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { IonApp, IonRouterOutlet } from '@ionic/angular';
import { ConfigService } from './core/config/config.service';
import { I18nService } from './core/i18n/i18n.service';
import { LayoutService } from './core/layout/layout.service';
import { SessionService } from './core/session/session.service';
import { AgentFabComponent } from './shared/components/agent-fab/agent-fab.component';
import { AppHeaderComponent } from './shared/components/app-header/app-header.component';
import { OverlayMenuComponent } from './shared/components/overlay-menu/overlay-menu.component';
import { SidebarComponent } from './shared/components/sidebar/sidebar.component';
import { TabBarComponent } from './shared/components/tab-bar/tab-bar.component';

/** App shell: header, persistent sidebar (desktop), routed page, overlay menu, tab bar (mobile), and the agent FAB. */
@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    IonApp,
    IonRouterOutlet,
    AppHeaderComponent,
    SidebarComponent,
    OverlayMenuComponent,
    TabBarComponent,
    AgentFabComponent,
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent {
  private readonly config = inject(ConfigService);
  private readonly i18n = inject(I18nService);
  readonly layout = inject(LayoutService);
  readonly session = inject(SessionService);

  readonly mainContentId = this.config.layout.mainContentId;
  readonly mainLabel = this.i18n.text('a11y.mainRegion');

  constructor() {
    this.session.refresh();
  }
}
