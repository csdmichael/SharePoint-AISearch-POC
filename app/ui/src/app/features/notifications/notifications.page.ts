import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { IonContent, IonIcon, IonLabel, IonSegment, IonSegmentButton } from '@ionic/angular';
import { Observable } from 'rxjs';
import { ApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { NotificationItem, NotificationPage, ResponseMode } from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CursorList } from '../../shared/util/cursor-list';
import { DisplayService } from '../../shared/util/display.service';

/** Outbox of notifications by status, with a preview of subject and body and the approve and send actions. */
@Component({
  selector: 'app-notifications-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonLabel, IonSegment, IonSegmentButton, BadgeComponent, StateViewComponent, TranslatePipe],
  templateUrl: './notifications.page.html',
  styleUrl: './notifications.page.scss',
  host: { class: 'ion-page' },
})
export class NotificationsPage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;
  readonly statuses = this.config.pages.notifications.statuses;

  readonly status = signal(this.config.pages.notifications.defaultStatus);
  readonly outbox = new CursorList<NotificationItem, NotificationPage>({
    key: () => (this.session.gate() === 'ready' ? this.status() : undefined),
    fetch: (key) => this.api.notifications(key),
  });

  readonly view = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.outbox.loading(),
      error: this.outbox.error(),
      empty: this.outbox.items().length === 0,
    }),
  );

  /** Items updated by approve or send, so the list reflects the latest status without refetching. */
  readonly overrides = signal<Record<string, NotificationItem>>({});
  readonly items = computed(() => this.outbox.items().map((item) => this.overrides()[item.id] ?? item));

  readonly selectedId = signal<string | null>(null);
  readonly selected = computed<NotificationItem | null>(() => this.items().find((item) => item.id === this.selectedId()) ?? null);

  readonly actionMode = signal<ResponseMode | null>(null);
  readonly mode = computed<ResponseMode | null>(() => this.actionMode() ?? this.outbox.page()?.mode ?? null);
  readonly modeBadge = computed(() => {
    const mode = this.mode();
    if (mode !== 'dryRun') {
      return null;
    }
    return { text: this.i18n.text('modeBadges.dryRun'), color: this.display.statusColor('dryRun') };
  });

  readonly acting = signal<string | null>(null);
  readonly actionError = signal<ApiError | null>(null);
  readonly actionErrorView = computed<ViewState | null>(() => {
    const error = this.actionError();
    return error ? { kind: 'error', gate: null, errorKind: error.kind } : null;
  });

  selectStatus(value: string): void {
    if (value === this.status()) {
      return;
    }
    this.status.set(value);
    this.selectedId.set(null);
    this.actionMode.set(null);
    this.actionError.set(null);
  }

  selectValue(event: { detail: { value?: unknown } }): string {
    const value = event.detail.value;
    return typeof value === 'string' ? value : this.status();
  }

  statusLabel(status: string): string {
    return this.i18n.text(`notifications.statuses.${status}`);
  }

  recipientText(item: NotificationItem): string {
    if (item.ownerName && item.ownerUpn) {
      return this.i18n.text('notifications.recipientFormat', { name: item.ownerName, upn: item.ownerUpn });
    }
    return item.to.join(', ') || this.i18n.text('states.notAvailable');
  }

  /** The most recent change to a notification: sent, else approved, else created. */
  lastChangedAt(item: NotificationItem): string | null {
    return item.sentAt ?? item.approvedAt ?? item.createdAt;
  }

  select(item: NotificationItem): void {
    this.selectedId.set(item.id);
  }

  canApprove(item: NotificationItem): boolean {
    return item.status === 'draft';
  }

  canSend(item: NotificationItem): boolean {
    return item.status === 'approved';
  }

  approve(item: NotificationItem): void {
    this.runAction(item.id, () => this.api.approveNotification(item.id));
  }

  send(item: NotificationItem): void {
    this.runAction(item.id, () => this.api.sendNotification(item.id));
  }

  retry(): void {
    this.session.refresh();
    this.outbox.reload();
  }

  private runAction(id: string, call: () => Observable<NotificationItem>): void {
    if (this.acting()) {
      return;
    }
    this.acting.set(id);
    this.actionError.set(null);
    call().subscribe({
      next: (notification) => {
        this.overrides.update((current) => ({ ...current, [notification.id]: notification }));
        this.actionMode.set(notification.mode);
        this.acting.set(null);
      },
      error: (error: unknown) => {
        this.actionError.set(toApiError(error));
        this.acting.set(null);
      },
    });
  }
}
