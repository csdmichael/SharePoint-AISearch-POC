import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IonContent, IonIcon, IonLabel, IonSegment, IonSegmentButton } from '@ionic/angular';
import { ApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { CleanupRecord, DocumentRef, ResponseMode } from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { NavigationService } from '../../core/navigation/navigation';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CursorList } from '../../shared/util/cursor-list';
import { DisplayService } from '../../shared/util/display.service';

interface DraftSummary {
  mode: ResponseMode;
  count: number;
}

/** Cleanup segments (duplicates, expiry, anomalies, exposure). Rows can be selected and drafted as notifications. */
@Component({
  selector: 'app-cleanup-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonLabel, IonSegment, IonSegmentButton, RouterLink, BadgeComponent, StateViewComponent, TranslatePipe],
  templateUrl: './cleanup.page.html',
  styleUrl: './cleanup.page.scss',
  host: { class: 'ion-page' },
})
export class CleanupPage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly navigation = inject(NavigationService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;
  readonly segments = this.config.pages.cleanup.segments;

  readonly segment = signal(this.config.pages.cleanup.defaultSegment);
  readonly records = new CursorList<CleanupRecord>({
    key: () => (this.session.gate() === 'ready' ? this.segment() : undefined),
    fetch: (key, cursor) => this.api.cleanup(key, cursor),
  });

  readonly view = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.records.loading(),
      error: this.records.error(),
      empty: this.records.items().length === 0,
    }),
  );

  readonly selectedIds = signal<ReadonlySet<string>>(new Set());
  readonly selectedCount = computed(() => this.selectedIds().size);
  readonly visibleIds = computed(() => this.records.items().flatMap((record) => recordIds(record)));

  readonly drafting = signal(false);
  readonly draftError = signal<ApiError | null>(null);
  readonly draftErrorView = computed<ViewState | null>(() => {
    const error = this.draftError();
    return error ? { kind: 'error', gate: null, errorKind: error.kind } : null;
  });
  readonly draftSummary = signal<DraftSummary | null>(null);
  readonly draftBadge = computed(() => {
    const summary = this.draftSummary();
    if (!summary) {
      return null;
    }
    const key = summary.mode === 'dryRun' ? 'dryRun' : 'live';
    return { text: this.i18n.text(`modeBadges.${key}`), color: this.display.statusColor(key) };
  });
  readonly draftText = computed(() => {
    const summary = this.draftSummary();
    if (!summary) {
      return '';
    }
    const key = summary.mode === 'dryRun' ? 'cleanup.draftDryRunSummary' : 'cleanup.draftSummary';
    return this.i18n.text(key, { count: this.i18n.number(summary.count) });
  });

  readonly separator = this.i18n.text('cleanup.separator');

  selectSegment(segmentId: string): void {
    if (segmentId === this.segment()) {
      return;
    }
    this.segment.set(segmentId);
    this.selectedIds.set(new Set());
    this.draftSummary.set(null);
    this.draftError.set(null);
  }

  selectValue(event: { detail: { value?: unknown } }): string {
    const value = event.detail.value;
    return typeof value === 'string' ? value : this.segment();
  }

  segmentLabel(segmentId: string): string {
    return this.i18n.text(`cleanup.segments.${segmentId}`);
  }

  isSelected(id: string): boolean {
    return this.selectedIds().has(id);
  }

  toggle(id: string): void {
    const next = new Set(this.selectedIds());
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.selectedIds.set(next);
  }

  selectAll(): void {
    this.selectedIds.set(new Set(this.visibleIds()));
  }

  clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  selectLabel(document: DocumentRef): string {
    return this.i18n.text('cleanup.selectRow', { name: document.name });
  }

  clusterTitle(canonical: DocumentRef): string {
    return this.i18n.text('cleanup.clusterTitle', { name: canonical.name });
  }

  canonicalOf(canonical: DocumentRef): string {
    return this.i18n.text('cleanup.canonicalOf', { name: canonical.name });
  }

  /** One line of detail per non-duplicate segment, built from the record's fields. */
  recordDetail(record: CleanupRecord): string {
    switch (record.segment) {
      case 'expiry':
        return this.i18n.text('cleanup.expiryDetail', {
          date: this.i18n.date(record.expirationDate),
          count: this.i18n.number(record.daysPastExpiry),
        });
      case 'anomalies':
        return this.i18n.text('cleanup.anomalyDetail', {
          score: this.i18n.number(record.score),
          contributions: record.contributions
            .map((item) => `${item.feature}: ${this.i18n.number(item.contribution)}`)
            .join(this.i18n.text('cleanup.listSeparator')),
        });
      case 'exposure':
        return this.i18n.text('cleanup.exposureDetail', {
          exposure: record.exposure,
          sensitivity: record.sensitivity ?? this.i18n.text('states.notAvailable'),
        });
      default:
        return '';
    }
  }

  documentPath(id: string): string {
    return this.navigation.documentPath(id);
  }

  draftNotifications(): void {
    const documentIds = [...this.selectedIds()];
    if (documentIds.length === 0 || this.drafting()) {
      return;
    }
    this.drafting.set(true);
    this.draftError.set(null);
    this.draftSummary.set(null);
    this.api.createDrafts({ segment: this.segment(), documentIds }).subscribe({
      next: (result) => {
        this.draftSummary.set({ mode: result.mode, count: result.items.length });
        this.selectedIds.set(new Set());
        this.drafting.set(false);
      },
      error: (error: unknown) => {
        this.draftError.set(toApiError(error));
        this.drafting.set(false);
      },
    });
  }

  retry(): void {
    this.session.refresh();
    this.records.reload();
  }

  notificationsRoute(): string {
    return this.navigation.routeFor('notifications');
  }
}

/** Selectable ids of a record: each duplicate member, or the single document for other segments. */
export function recordIds(record: CleanupRecord): string[] {
  return record.segment === 'duplicates' ? record.members.map((member) => member.id) : [record.document.id];
}
