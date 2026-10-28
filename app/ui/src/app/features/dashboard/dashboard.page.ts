import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { IonContent, IonIcon } from '@ionic/angular';
import { forkJoin } from 'rxjs';
import { ApiService } from '../../core/api/api.service';
import { ApiError, asApiError, toApiError } from '../../core/api/api-error';
import { DocumentRef, HygieneFinding } from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { LayoutService } from '../../core/layout/layout.service';
import { NavigationService } from '../../core/navigation/navigation';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { DisplayService } from '../../shared/util/display.service';

interface FindingDetailState {
  loading: boolean;
  error: ApiError | null;
  documents: DocumentRef[];
}

interface KpiCard {
  key: string;
  label: string;
  value: number | null;
}

/** Governance dashboard: KPI cards (labels from /policy, values from /hygiene) and expandable hygiene findings. */
@Component({
  selector: 'app-dashboard-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, RouterLink, BadgeComponent, StateViewComponent, TranslatePipe],
  templateUrl: './dashboard.page.html',
  styleUrl: './dashboard.page.scss',
  host: { class: 'ion-page' },
})
export class DashboardPage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly layout = inject(LayoutService);
  readonly navigation = inject(NavigationService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;

  readonly summary = rxResource({
    params: () => (this.session.gate() === 'ready' ? true : undefined),
    stream: () => forkJoin({ policy: this.api.policy(), hygiene: this.api.hygiene() }),
  });
  private readonly summaryData = computed(() => this.summary.hasValue() ? this.summary.value() : undefined);

  readonly view = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.summary.isLoading(),
      error: asApiError(this.summary.error()),
      empty: false,
    }),
  );

  readonly metrics = computed<KpiCard[]>(() => {
    const data = this.summaryData();
    if (!data) {
      return [];
    }
    return data.policy.hygiene.metrics.map((metric) => ({
      key: metric.key,
      label: metric.label,
      value: data.hygiene.metrics.find((entry) => entry.key === metric.key)?.value ?? null,
    }));
  });

  readonly findings = computed<HygieneFinding[]>(() => this.summaryData()?.hygiene.findings ?? []);
  readonly generatedAt = computed(() => {
    const value = this.summaryData()?.hygiene.asOfDate;
    return value ? this.i18n.text('dashboard.generatedAt', { date: this.i18n.date(value) }) : null;
  });

  readonly expanded = signal<ReadonlySet<string>>(new Set());
  readonly details = signal<Record<string, FindingDetailState>>({});

  formatValue(value: number | null): string {
    return value === null ? this.i18n.text('states.notAvailable') : this.i18n.number(value);
  }

  severityLabel(severity: string): string {
    return this.display.label('severity', severity);
  }

  severityColor(severity: string): string {
    return this.display.severityColor(severity);
  }

  countLabel(count: number): string {
    return this.i18n.text('dashboard.findingDocumentCount', { count: this.i18n.number(count) });
  }

  isExpanded(id: string): boolean {
    return this.expanded().has(id);
  }

  toggleFinding(id: string): void {
    const next = new Set(this.expanded());
    if (next.has(id)) {
      next.delete(id);
      this.expanded.set(next);
      return;
    }
    next.add(id);
    this.expanded.set(next);
    if (!this.details()[id]) {
      this.loadFinding(id);
    }
  }

  loadFinding(id: string): void {
    this.setDetail(id, { loading: true, error: null, documents: [] });
    this.api
      .hygieneFinding(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (detail) => this.setDetail(id, { loading: false, error: null, documents: detail.documents }),
        error: (error: unknown) => this.setDetail(id, { loading: false, error: toApiError(error), documents: [] }),
      });
  }

  findingView(id: string): ViewState {
    const detail = this.details()[id];
    return resolveViewState(this.session.gate(), {
      loading: detail?.loading ?? false,
      error: detail?.error ?? null,
      empty: (detail?.documents.length ?? 0) === 0,
    });
  }

  findingDocuments(id: string): DocumentRef[] {
    return this.details()[id]?.documents ?? [];
  }

  retry(): void {
    this.session.refresh();
    this.summary.reload();
  }

  private setDetail(id: string, state: FindingDetailState): void {
    this.details.update((current) => ({ ...current, [id]: state }));
  }
}
