import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { Router, NavigationEnd } from '@angular/router';
import { IonFab, IonFabButton, IonIcon } from '@ionic/angular';
import { filter, map } from 'rxjs';
import { ConfigService } from '../../../core/config/config.service';
import { I18nService } from '../../../core/i18n/i18n.service';
import { isFabVisible } from '../../../core/navigation/navigation';

type FabVertical = 'top' | 'bottom';
type FabHorizontal = 'start' | 'end';

/** Foundry agent floating button. Position, icon, label, route, and hidden routes come from agent.json. */
@Component({
  selector: 'app-agent-fab',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonFab, IonFabButton, IonIcon],
  template: `
    @if (visible()) {
      <ion-fab class="agent-fab" data-testid="agent-fab" [vertical]="vertical" [horizontal]="horizontal" slot="fixed">
        <ion-fab-button [attr.aria-label]="label" [attr.title]="label" (click)="open()">
          <ion-icon [name]="icon" aria-hidden="true" />
        </ion-fab-button>
      </ion-fab>
    }
  `,
  styleUrl: './agent-fab.component.scss',
})
export class AgentFabComponent {
  private readonly config = inject(ConfigService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);

  private readonly fab = this.config.agent.fab;
  readonly icon = this.fab.icon;
  readonly label = this.i18n.text(this.fab.labelKey);
  readonly vertical = this.fab.position.split('-')[0] as FabVertical;
  readonly horizontal = this.fab.position.split('-')[1] as FabHorizontal;

  private readonly url = toSignal(
    this.router.events.pipe(
      filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );
  readonly visible = computed(() => isFabVisible(this.url(), this.fab));

  open(): void {
    void this.router.navigateByUrl(this.fab.route);
  }
}
