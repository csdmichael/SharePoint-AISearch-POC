import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { IonIcon } from '@ionic/angular';
import { LayoutService } from '../../../core/layout/layout.service';
import { NavigationService } from '../../../core/navigation/navigation';
import { I18nService } from '../../../core/i18n/i18n.service';
import { TranslatePipe } from '../../pipes/translate.pipe';

/** Bottom tab bar for the mobile layout. Shows the items listed in layout.mobileTabIds. */
@Component({
  selector: 'app-tab-bar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, RouterLinkActive, IonIcon, TranslatePipe],
  template: `
    @if (layout.isMobile()) {
      <nav class="tab-bar" data-testid="mobile-tab-bar" [attr.aria-label]="tabBarLabel">
        @for (item of items(); track item.id) {
          <a class="tab-bar__item" [routerLink]="item.route" routerLinkActive="is-active" [attr.data-nav-id]="item.id">
            <ion-icon [name]="item.icon" aria-hidden="true" />
            <span class="tab-bar__label">{{ item.labelKey | t }}</span>
          </a>
        }
      </nav>
    }
  `,
  styleUrl: './tab-bar.component.scss',
})
export class TabBarComponent {
  private readonly navigation = inject(NavigationService);
  private readonly i18n = inject(I18nService);
  readonly layout = inject(LayoutService);

  readonly tabBarLabel = this.i18n.text('header.tabBarLabel');
  readonly items = computed(() => this.navigation.sets().tabBar);
}
