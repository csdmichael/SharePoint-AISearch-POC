import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  IonButton,
  IonButtons,
  IonContent,
  IonHeader,
  IonIcon,
  IonItem,
  IonLabel,
  IonList,
  IonListHeader,
  IonMenu,
  IonTitle,
  IonToolbar,
  MenuController,
} from '@ionic/angular';
import { ConfigService } from '../../../core/config/config.service';
import { I18nService } from '../../../core/i18n/i18n.service';
import { LayoutService } from '../../../core/layout/layout.service';
import { NavigationService } from '../../../core/navigation/navigation';
import { TranslatePipe } from '../../pipes/translate.pipe';

/** Overlay menu for tablet and mobile. Lists every navigation item. Disabled on desktop, where the sidebar is shown. */
@Component({
  selector: 'app-overlay-menu',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    IonMenu,
    IonHeader,
    IonToolbar,
    IonTitle,
    IonButtons,
    IonButton,
    IonIcon,
    IonContent,
    IonList,
    IonListHeader,
    IonItem,
    IonLabel,
    TranslatePipe,
  ],
  template: `
    <ion-menu
      data-testid="overlay-menu"
      [menuId]="menuId"
      [contentId]="contentId"
      type="overlay"
      side="start"
      [disabled]="layout.isDesktop()"
    >
      <ion-header>
        <ion-toolbar>
          <ion-title>{{ 'header.overlayTitle' | t }}</ion-title>
          <ion-buttons slot="end">
            <ion-button [attr.aria-label]="'buttons.closeMenu' | t" (click)="close()">
              <ion-icon slot="icon-only" [name]="icons.close" aria-hidden="true" />
            </ion-button>
          </ion-buttons>
        </ion-toolbar>
      </ion-header>
      <ion-content>
        <nav [attr.aria-label]="'header.overlayTitle' | t">
          @for (group of groups(); track group.groupId) {
            <ion-list-header>{{ group.groupLabelKey | t }}</ion-list-header>
            <ion-list>
              @for (item of group.items; track item.id) {
                <ion-item button detail="false" [routerLink]="item.route" [attr.data-nav-id]="item.id" (click)="close()">
                  <ion-icon slot="start" [name]="item.icon" aria-hidden="true" />
                  <ion-label>{{ item.labelKey | t }}</ion-label>
                </ion-item>
              }
            </ion-list>
          }
        </nav>
      </ion-content>
    </ion-menu>
  `,
})
export class OverlayMenuComponent {
  private readonly config = inject(ConfigService);
  private readonly menuController = inject(MenuController);
  private readonly navigation = inject(NavigationService);
  readonly layout = inject(LayoutService);

  readonly menuId = this.config.layout.overlayMenuId;
  readonly contentId = this.config.layout.mainContentId;
  readonly icons = this.config.layout.icons;
  readonly groups = computed(() => this.navigation.groupedItems(this.navigation.sets().overlay));

  close(): void {
    void this.menuController.close(this.menuId);
  }
}
