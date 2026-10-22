import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { IonIcon } from '@ionic/angular';
import { I18nService } from '../../../core/i18n/i18n.service';
import { NavigationService } from '../../../core/navigation/navigation';
import { TranslatePipe } from '../../pipes/translate.pipe';

/** Persistent left navigation for the desktop layout. Every navigation item is listed, grouped as configured. */
@Component({
  selector: 'app-sidebar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, RouterLinkActive, IonIcon, TranslatePipe],
  template: `
    <nav class="sidebar" data-testid="sidebar" [attr.aria-label]="sidebarLabel">
      @for (group of groups(); track group.groupId) {
        <div class="sidebar__group">
          <h2 class="sidebar__group-title">{{ group.groupLabelKey | t }}</h2>
          <ul class="sidebar__list">
            @for (item of group.items; track item.id) {
              <li>
                <a class="sidebar__link" [routerLink]="item.route" routerLinkActive="is-active" [attr.data-nav-id]="item.id">
                  <ion-icon [name]="item.icon" aria-hidden="true" />
                  <span>{{ item.labelKey | t }}</span>
                </a>
              </li>
            }
          </ul>
        </div>
      }
    </nav>
  `,
  styleUrl: './sidebar.component.scss',
})
export class SidebarComponent {
  private readonly i18n = inject(I18nService);
  private readonly navigation = inject(NavigationService);

  readonly sidebarLabel = this.i18n.text('header.sidebarLabel');
  readonly groups = computed(() => this.navigation.groupedItems(this.navigation.sets().sidebar));
}
