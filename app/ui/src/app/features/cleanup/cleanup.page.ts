import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { NgTemplateOutlet } from '@angular/common';
import { RouterLink } from '@angular/router';
import { IonContent, IonIcon, IonLabel, IonSegment, IonSegmentButton } from '@ionic/angular';
import { forkJoin } from 'rxjs';
import { ApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { draftTemplateId } from '../../core/api/api.mappers';
import { CleanupDraftTemplates, CleanupRecord, DocumentPreview, DocumentRef, ResponseMode } from '../../core/api/models/api.models';
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

export interface ComparisonPair {
  canonical: DocumentRef;
  duplicate: DocumentRef;
}

/** In-page viewer state for one document pane. 'media' covers PDF (iframe) and video (video tag); both use objectUrl. */
export interface DocumentViewerState {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'unsupported';
  objectUrl: string | null;
  textContent: string | null;
  preview: DocumentPreview | null;
  error: string | null;
}

const IDLE_VIEWER: DocumentViewerState = { status: 'idle', objectUrl: null, textContent: null, preview: null, error: null };

/** Cleanup segments (duplicates, expiry, anomalies, exposure). Rows can be selected and drafted as notifications. */
@Component({
  selector: 'app-cleanup-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonLabel, IonSegment, IonSegmentButton, RouterLink, NgTemplateOutlet, BadgeComponent, StateViewComponent, TranslatePipe],
  templateUrl: './cleanup.page.html',
  styleUrl: './cleanup.page.scss',
  host: { class: 'ion-page' },
})
export class CleanupPage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  private readonly sanitizer = inject(DomSanitizer);
  readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly navigation = inject(NavigationService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;
  readonly segments = this.config.pages.cleanup.segments;

  readonly selectedComparison = signal<ComparisonPair | null>(null);
  readonly viewerTab = signal<'viewer' | 'metadata'>('viewer');
  readonly canonicalViewer = signal<DocumentViewerState>(IDLE_VIEWER);
  readonly duplicateViewer = signal<DocumentViewerState>(IDLE_VIEWER);

  readonly segment = signal(this.config.pages.cleanup.defaultSegment);

  constructor() {
    effect(() => {
      this.api.siteContext();
      this.selectedIds.set(new Set());
      this.closeComparison();
      this.draftSummary.set(null);
      this.draftError.set(null);
      this.records.reload();
    });
  }

  readonly records = new CursorList<CleanupRecord>({
    key: () => (this.session.gate() === 'ready' ? `${this.api.siteContext() ?? '__default__'}:${this.segment()}` : undefined),
    fetch: (key) => this.api.cleanup(key.slice(key.indexOf(':') + 1)),
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
  readonly templates: CleanupDraftTemplates = this.config.pages.cleanup.draftTemplates;
  readonly visibleIds = computed(() => this.records.items().flatMap((record) => draftableIds(record, this.templates)));

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

  openComparison(canonical: DocumentRef, duplicate: DocumentRef): void {
    this.selectedComparison.set({ canonical, duplicate });
    this.viewerTab.set('viewer');
    this.loadViewer(canonical, this.canonicalViewer);
    this.loadViewer(duplicate, this.duplicateViewer);
  }

  closeComparison(): void {
    this.selectedComparison.set(null);
    this.revokeAndReset(this.canonicalViewer);
    this.revokeAndReset(this.duplicateViewer);
  }

  setViewerTab(tab: 'viewer' | 'metadata'): void {
    this.viewerTab.set(tab);
  }

  fileExtension(name: string): string {
    const idx = name.lastIndexOf('.');
    return idx >= 0 ? name.substring(idx).toLowerCase() : '';
  }

  fileTypeInfo(name: string): { label: string; icon: string; color: string; viewerType: 'pdf' | 'office' | 'text' | 'media' | 'other' } {
    const ext = this.fileExtension(name);
    switch (ext) {
      case '.docx':
      case '.doc':
        return { label: 'Word Document', icon: 'document-text-outline', color: '#2B579A', viewerType: 'office' };
      case '.pptx':
      case '.ppt':
        return { label: 'PowerPoint Slide', icon: 'easel-outline', color: '#D24726', viewerType: 'office' };
      case '.xlsx':
      case '.xls':
        return { label: 'Excel Workbook', icon: 'grid-outline', color: '#217346', viewerType: 'office' };
      case '.pdf':
        return { label: 'PDF Document', icon: 'document-outline', color: '#E81123', viewerType: 'pdf' };
      case '.vtt':
      case '.txt':
        return { label: 'Transcript / Text', icon: 'reader-outline', color: '#0078D4', viewerType: 'text' };
      case '.mp4':
        return { label: 'Video Recording', icon: 'videocam-outline', color: '#5C2D91', viewerType: 'media' };
      default:
        return { label: 'File Document', icon: 'document-outline', color: '#6B7280', viewerType: 'other' };
    }
  }

  /** Angular requires an explicitly trusted SafeResourceUrl for iframe src (used for the PDF viewer). */
  safeResourceUrl(url: string | null): SafeResourceUrl | null {
    return url ? this.sanitizer.bypassSecurityTrustResourceUrl(url) : null;
  }

  /** Loads a document into its pane for in-page rendering: a blob (pdf/video/text) or a structured preview (office). */
  private loadViewer(document: DocumentRef, target: ReturnType<typeof signal<DocumentViewerState>>): void {
    this.revokeAndReset(target);
    const viewerType = this.fileTypeInfo(document.name).viewerType;
    if (viewerType === 'other') {
      target.set({ ...IDLE_VIEWER, status: 'unsupported' });
      return;
    }
    target.set({ ...IDLE_VIEWER, status: 'loading' });
    if (viewerType === 'office') {
      this.api.documentPreview(document.id).subscribe({
        next: (preview) => target.set({ ...IDLE_VIEWER, status: 'ready', preview }),
        error: (error: unknown) => target.set({ ...IDLE_VIEWER, status: 'error', error: toApiError(error).kind }),
      });
      return;
    }
    this.api.documentContent(document.id).subscribe({
      next: (blob) => {
        if (viewerType === 'text') {
          blob.text().then((textContent) => target.set({ ...IDLE_VIEWER, status: 'ready', textContent }));
        } else {
          const objectUrl = URL.createObjectURL(blob);
          target.set({ ...IDLE_VIEWER, status: 'ready', objectUrl });
        }
      },
      error: (error: unknown) => target.set({ ...IDLE_VIEWER, status: 'error', error: toApiError(error).kind }),
    });
  }

  private revokeAndReset(target: ReturnType<typeof signal<DocumentViewerState>>): void {
    const current = target();
    if (current.objectUrl) {
      URL.revokeObjectURL(current.objectUrl);
    }
    target.set(IDLE_VIEWER);
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
      case 'expiry': {
        const date = this.i18n.date(record.date);
        const count = record.days === null ? this.i18n.text('states.notAvailable') : this.i18n.number(record.days);
        return record.reason === 'expired'
          ? this.i18n.text('cleanup.expiryDetail', { date, count })
          : this.i18n.text('cleanup.reviewOverdueDetail', { date, count });
      }
      case 'anomalies':
        return this.i18n.text('cleanup.anomalyDetail', {
          score: this.i18n.number(record.score),
          contributions: record.contributions
            .map((item) => `${item.feature}: ${this.i18n.number(item.contribution)}`)
            .join(this.i18n.text('cleanup.listSeparator')),
        });
      case 'exposure':
        return this.i18n.text('cleanup.exposureDetail', {
          detail: record.detail,
          severity: this.display.label('severity', record.severity),
        });
      default:
        return '';
    }
  }

  documentPath(id: string): string {
    return this.navigation.documentPath(id);
  }

  /** Selected documents, grouped by the notification template each one needs. One request per template. */
  draftNotifications(): void {
    const groups = this.draftGroups();
    if (groups.size === 0 || this.drafting()) {
      return;
    }
    this.drafting.set(true);
    this.draftError.set(null);
    this.draftSummary.set(null);
    forkJoin([...groups].map(([templateId, documentIds]) => this.api.createDrafts(templateId, documentIds))).subscribe({
      next: (results) => {
        this.draftSummary.set({
          mode: results[0].mode,
          count: results.reduce((total, result) => total + result.created.length, 0),
        });
        this.selectedIds.set(new Set());
        this.drafting.set(false);
      },
      error: (error: unknown) => {
        this.draftError.set(toApiError(error));
        this.drafting.set(false);
      },
    });
  }

  isDraftable(record: CleanupRecord, documentId: string): boolean {
    return draftTemplateId(record, documentId, this.templates) !== null;
  }

  private draftGroups(): Map<string, string[]> {
    const groups = new Map<string, string[]>();
    for (const documentId of this.selectedIds()) {
      for (const record of this.records.items()) {
        const templateId = draftTemplateId(record, documentId, this.templates);
        if (templateId !== null) {
          groups.set(templateId, [...(groups.get(templateId) ?? []), documentId]);
          break;
        }
      }
    }
    return groups;
  }

  retry(): void {
    this.session.refresh();
    this.records.reload();
  }

  notificationsRoute(): string {
    return this.navigation.routeFor('notifications');
  }
}

/** Document ids in a record that have a notification template. Only those rows can be selected for drafting. */
export function draftableIds(record: CleanupRecord, templates: CleanupDraftTemplates): string[] {
  const ids = record.segment === 'duplicates' ? record.members.map((member) => member.id) : [record.document.id];
  return ids.filter((id) => draftTemplateId(record, id, templates) !== null);
}
