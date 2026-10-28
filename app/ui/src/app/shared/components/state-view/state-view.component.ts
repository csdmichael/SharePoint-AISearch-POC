import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { IonButton, IonIcon, IonSpinner } from '@ionic/angular';
import { ConfigService } from '../../../core/config/config.service';
import { SessionService, ViewState } from '../../../core/session/session.service';
import { TranslatePipe } from '../../pipes/translate.pipe';

interface StateCopy {
  titleKey: string;
  bodyKey: string;
  icon: string;
  retry: boolean;
  signIn: boolean;
}

/**
 * Shows every state that replaces page content: checking, loading, API unreachable (with retry),
 * sign-in required, sign-in not configured, request failed, not found, and empty.
 * All text comes from strings.json and all icons from layout.json.
 */
@Component({
  selector: 'app-state-view',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonButton, IonIcon, IonSpinner, TranslatePipe],
  template: `
    @if (state().kind !== 'ready') {
      <section class="state-view" data-testid="state-view" role="status" [attr.data-state]="state().kind" [attr.data-gate]="state().gate" [attr.data-error]="state().errorKind">
        @switch (state().kind) {
          @case ('loading') {
            <ion-spinner aria-hidden="true" />
            <p class="state-view__text">{{ loadingKey() | t }}</p>
          }
          @case ('empty') {
            <span class="state-view__icon-wrap" aria-hidden="true"><ion-icon class="state-view__icon" [name]="icons.empty" /></span>
            <p class="state-view__text" data-testid="state-empty">{{ emptyKey() | t }}</p>
          }
          @default {
            <span class="state-view__icon-wrap" aria-hidden="true"><ion-icon class="state-view__icon" [name]="copy().icon" /></span>
            <h2 class="state-view__title" data-testid="state-title">{{ copy().titleKey | t }}</h2>
            <p class="state-view__text" data-testid="state-body">{{ copy().bodyKey | t }}</p>
            @if (copy().retry || copy().signIn) {
              <div class="state-view__actions">
                @if (copy().retry) {
                  <ion-button data-testid="state-retry" (click)="retry.emit()">
                    <ion-icon slot="start" [name]="icons.retry" aria-hidden="true" />
                    {{ 'buttons.retry' | t }}
                  </ion-button>
                }
                @if (copy().signIn) {
                  <ion-button data-testid="state-sign-in" [disabled]="!session.auth.configured" (click)="signIn()">
                    <ion-icon slot="start" [name]="icons.signIn" aria-hidden="true" />
                    {{ 'buttons.signIn' | t }}
                  </ion-button>
                }
              </div>
            }
          }
        }
      </section>
    }
  `,
  styleUrl: './state-view.component.scss',
})
export class StateViewComponent {
  private readonly config = inject(ConfigService);
  readonly session = inject(SessionService);

  readonly state = input.required<ViewState>();
  readonly emptyKey = input('states.empty');
  readonly retry = output<void>();

  readonly icons = this.config.layout.icons;

  readonly loadingKey = computed(() => (this.state().gate === 'checking' ? 'states.checking' : 'states.loading'));

  readonly copy = computed<StateCopy>(() => {
    const state = this.state();
    const icons = this.icons;
    switch (state.gate) {
      case 'apiUnreachable':
        return { titleKey: 'states.apiUnreachable.title', bodyKey: 'states.apiUnreachable.body', icon: icons.warning, retry: true, signIn: false };
      case 'signInRequired':
        return { titleKey: 'states.signInRequired.title', bodyKey: 'states.signInRequired.body', icon: icons.locked, retry: false, signIn: true };
      case 'authNotConfigured':
        return { titleKey: 'states.authNotConfigured.title', bodyKey: 'states.authNotConfigured.body', icon: icons.locked, retry: false, signIn: false };
      case 'authError':
        return { titleKey: 'states.authError.title', bodyKey: 'states.authError.body', icon: icons.warning, retry: false, signIn: false };
      default:
        break;
    }
    if (state.kind === 'error' && state.errorKind === 'notFound') {
      return { titleKey: 'states.notFound.title', bodyKey: 'states.notFound.body', icon: icons.notFound, retry: false, signIn: false };
    }
    return { titleKey: 'states.requestFailed.title', bodyKey: 'states.requestFailed.body', icon: icons.warning, retry: true, signIn: false };
  });

  signIn(): void {
    void this.session.signIn();
  }
}
