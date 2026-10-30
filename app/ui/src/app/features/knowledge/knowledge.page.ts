import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { IonContent, IonIcon, IonSpinner } from '@ionic/angular';
import { ApiError, asApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import {
  KnowledgeDraft,
  KnowledgeIndexingStatus,
  KnowledgeMessage,
  KnowledgeOrigin,
  KnowledgePublishResult,
} from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { NavigationService } from '../../core/navigation/navigation';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { DisplayService } from '../../shared/util/display.service';
import { safeHttpUrl } from '../../shared/util/url';
import {
  INDEX_STEPS,
  KnowledgeErrorKey,
  KnowledgeFieldName,
  KnowledgeForm,
  buildPublishRequest,
  formFromDraft,
  indexStepState,
  initials,
  isTerminalStage,
  originOf,
  toggleSelection,
  validateForm,
} from './knowledge.logic';

type Step = 'select' | 'extracting' | 'extractFailed' | 'review' | 'done';

interface FieldSpec {
  name: KnowledgeFieldName;
  kind: 'text' | 'area' | 'select' | 'date' | 'email';
  /** Key in the draft's origins; null when the value is not extracted (so no origin chip is shown). */
  origin: string | null;
  error: KnowledgeErrorKey | null;
  rows?: number;
  wide?: boolean;
}

const POLL_INTERVAL_MS = 5000;
const MAX_POLLS = 120;
const FIELDS: FieldSpec[] = [
  { name: 'title', kind: 'text', origin: 'title', error: 'title', wide: true },
  { name: 'executiveSummary', kind: 'area', origin: 'executiveSummary', error: 'executiveSummary', rows: 3, wide: true },
  { name: 'category', kind: 'select', origin: 'category', error: 'category' },
  { name: 'department', kind: 'select', origin: 'department', error: null },
  { name: 'product', kind: 'text', origin: 'product', error: null },
  { name: 'sensitivity', kind: 'select', origin: 'sensitivity', error: 'sensitivity' },
  { name: 'issueContext', kind: 'area', origin: 'issueContext', error: null, rows: 3, wide: true },
  { name: 'rootCause', kind: 'area', origin: 'rootCause', error: null, rows: 2, wide: true },
  { name: 'decision', kind: 'area', origin: 'decision', error: null, rows: 2, wide: true },
  { name: 'recommendedAction', kind: 'area', origin: 'recommendedAction', error: 'content', rows: 3, wide: true },
  { name: 'keyFacts', kind: 'area', origin: 'keyFacts', error: null, rows: 4, wide: true },
  { name: 'ownerUpn', kind: 'email', origin: 'owner', error: 'owner' },
  { name: 'reviewDate', kind: 'date', origin: 'reviewDate', error: 'reviewDate' },
  { name: 'tags', kind: 'text', origin: 'tags', error: null, wide: true },
  { name: 'sourceDescription', kind: 'text', origin: 'sourceDescription', error: null, wide: true },
];

/**
 * Knowledge Capture: Select a few messages of a simulated Teams conversation, Save as Knowledge, review and edit the
 * AI draft, publish to SharePoint, then watch it become available to the existing AI assistant.
 */
@Component({
  selector: 'app-knowledge-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonSpinner, BadgeComponent, StateViewComponent, TranslatePipe],
  templateUrl: './knowledge.page.html',
  styleUrl: './knowledge.page.scss',
  host: { class: 'ion-page' },
})
export class KnowledgePage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  private readonly document = inject(DOCUMENT);
  private readonly router = inject(Router);
  private readonly navigation = inject(NavigationService);
  private readonly destroyRef = inject(DestroyRef);
  readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;
  readonly fields = FIELDS;
  readonly indexSteps = INDEX_STEPS;
  readonly origins: KnowledgeOrigin[] = ['source', 'ai', 'default', 'unknown'];

  readonly settings = rxResource({
    params: () => (this.session.gate() === 'ready' ? 'ready' : undefined),
    stream: () => this.api.knowledgeConfig(),
  });
  readonly settingsData = computed(() => (this.settings.hasValue() ? this.settings.value() : undefined));
  readonly view = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.settings.isLoading(),
      error: asApiError(this.settings.error()),
      empty: false,
    }),
  );
  readonly conversation = computed(() => this.settingsData()?.demo.conversation ?? null);
  readonly messages = computed<KnowledgeMessage[]>(() => this.conversation()?.messages ?? []);

  readonly step = signal<Step>('select');
  readonly selectedIds = signal<string[]>([]);
  readonly selectedCount = computed(() => this.selectedIds().length);
  readonly maxMessages = computed(() => this.settingsData()?.extraction.maxMessages ?? 1);
  readonly canSave = computed(() => this.selectedCount() > 0 && this.selectedCount() <= this.maxMessages());

  readonly draft = signal<KnowledgeDraft | null>(null);
  readonly extraction = signal<{ label: string; demo: boolean; provider: string; warnings: string[] } | null>(null);
  readonly extractError = signal<ApiError | null>(null);
  readonly form = signal<KnowledgeForm | null>(null);
  readonly edited = signal<ReadonlySet<string>>(new Set<string>());
  readonly attested = signal(false);
  readonly authoritative = signal(true);
  readonly showErrors = signal(false);
  readonly publishing = signal(false);
  readonly publishError = signal<ApiError | null>(null);

  readonly errors = computed<KnowledgeErrorKey[]>(() => {
    const form = this.form();
    const data = this.settingsData();
    if (!form || !data) {
      return [];
    }
    return validateForm(form, data.review, this.attested(), data.taxonomy.sensitivities, data.taxonomy.categories);
  });
  readonly visibleErrors = computed<KnowledgeErrorKey[]>(() => (this.showErrors() ? this.errors() : []));
  readonly lowConfidence = computed(() => {
    const draft = this.draft();
    const threshold = this.settingsData()?.review.lowConfidenceThreshold ?? 0;
    return draft !== null && draft.confidence < threshold;
  });
  readonly confidenceText = computed(() =>
    this.i18n.text('knowledge.review.confidence', { value: `${Math.round((this.draft()?.confidence ?? 0) * 100)}%` }),
  );

  readonly result = signal<KnowledgePublishResult | null>(null);
  readonly indexing = signal<KnowledgeIndexingStatus | null>(null);
  readonly refreshing = signal(false);
  readonly usedDemoConversation = signal(false);
  private polls = 0;

  constructor() {
    effect((onCleanup) => {
      const result = this.result();
      const status = this.indexing();
      if (!result || !status || isTerminalStage(status.stage)) {
        return;
      }
      const timer = globalThis.setInterval(() => untracked(() => this.pollIndexing()), POLL_INTERVAL_MS);
      onCleanup(() => globalThis.clearInterval(timer));
    });
    this.destroyRef.onDestroy(() => this.polls = MAX_POLLS);
  }

  // ---- Select ---------------------------------------------------------------------------------------------------

  isSelected(id: string): boolean {
    return this.selectedIds().includes(id);
  }

  toggle(id: string): void {
    this.selectedIds.update((current) => toggleSelection(current, id));
  }

  initialsOf(name: string): string {
    return initials(name);
  }

  messageLabel(message: KnowledgeMessage): string {
    return this.i18n.text('knowledge.select.messageLabel', { author: message.author });
  }

  selectedText(): string {
    return this.i18n.text('knowledge.select.selected', { count: this.selectedCount() });
  }

  saveAsKnowledge(): void {
    const data = this.settingsData();
    const conversation = this.conversation();
    if (!data || !conversation || !this.canSave()) {
      return;
    }
    const chosen = this.messages().filter((message) => this.isSelected(message.id));
    this.usedDemoConversation.set(conversation.keyMessageIds.every((id) => this.isSelected(id)));
    this.extractError.set(null);
    this.step.set('extracting');
    this.api
      .knowledgeExtract({
        conversationId: conversation.id,
        sourceDescription: null,
        messages: chosen.map((message) => ({ id: message.id, author: message.author, role: message.role, text: message.text, postedAt: message.postedAt })),
      })
      .subscribe({
        next: (response) => {
          this.extraction.set({ label: response.providerLabel, demo: response.demo, provider: response.provider, warnings: response.warnings });
          this.openReview(response.draft);
        },
        error: (error: unknown) => {
          this.extractError.set(toApiError(error));
          this.step.set('extractFailed');
        },
      });
  }

  startBlankDraft(): void {
    this.api.knowledgeBlankDraft().subscribe({
      next: (draft) => {
        this.extraction.set({ label: '', demo: false, provider: 'manual', warnings: [] });
        this.usedDemoConversation.set(false);
        this.openReview(draft);
      },
      error: (error: unknown) => this.extractError.set(toApiError(error)),
    });
  }

  private openReview(draft: KnowledgeDraft): void {
    this.draft.set(draft);
    this.form.set(formFromDraft(draft));
    this.edited.set(new Set<string>());
    this.attested.set(false);
    this.authoritative.set(true);
    this.showErrors.set(false);
    this.publishError.set(null);
    this.step.set('review');
  }

  backToSelection(): void {
    this.step.set('select');
    this.draft.set(null);
    this.form.set(null);
    this.publishError.set(null);
    this.extractError.set(null);
  }

  // ---- Review ---------------------------------------------------------------------------------------------------

  value(name: KnowledgeFieldName): string {
    return this.form()?.[name] ?? '';
  }

  onInput(spec: FieldSpec, event: Event): void {
    const target = event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
    this.form.update((form) => (form ? { ...form, [spec.name]: target.value } : form));
    if (spec.origin) {
      this.edited.update((current) => new Set([...current, spec.origin as string]));
    }
  }

  options(name: KnowledgeFieldName): string[] {
    const taxonomy = this.settingsData()?.taxonomy;
    const current = this.value(name);
    const base = name === 'category' ? taxonomy?.categories : name === 'department' ? taxonomy?.departments : taxonomy?.sensitivities;
    return [...new Set([...(base ?? []), ...(current ? [current] : [])])];
  }

  fieldOrigin(spec: FieldSpec): KnowledgeOrigin | null {
    return spec.origin ? originOf(this.draft(), spec.origin, this.edited()) : null;
  }

  fieldError(spec: FieldSpec): string | null {
    if (!spec.error || !this.visibleErrors().includes(spec.error)) {
      return null;
    }
    return this.i18n.text(`knowledge.errors.${spec.error === 'owner' ? 'owner' : spec.error}`, { months: this.settingsData()?.review.maxMonths ?? 0 });
  }

  originLabel(origin: KnowledgeOrigin): string {
    return this.i18n.text(`knowledge.origin.${origin}`);
  }

  ownerMentionText(): string {
    return this.i18n.text('knowledge.review.ownerMention', { name: this.draft()?.ownerMention ?? '' });
  }

  setAttested(event: Event): void {
    this.attested.set((event.target as HTMLInputElement).checked);
  }

  setAuthoritative(event: Event): void {
    this.authoritative.set((event.target as HTMLInputElement).checked);
  }

  publish(): void {
    const form = this.form();
    if (!form || this.publishing()) {
      return;
    }
    this.showErrors.set(true);
    if (this.errors().length > 0) {
      return;
    }
    const extraction = this.extraction();
    this.publishError.set(null);
    this.publishing.set(true);
    this.api
      .knowledgePublish(
        buildPublishRequest(form, {
          confidence: this.draft()?.confidence ?? 0,
          provider: extraction?.provider ?? 'manual',
          selectedMessageCount: this.selectedCount(),
          authoritative: this.authoritative(),
          attested: this.attested(),
        }),
      )
      .subscribe({
        next: (result) => {
          this.publishing.set(false);
          this.polls = 0;
          this.result.set(result);
          this.indexing.set(result.indexing);
          this.step.set('done');
        },
        error: (error: unknown) => {
          this.publishing.set(false);
          this.publishError.set(toApiError(error));
        },
      });
  }

  publishErrorText(): string {
    const error = this.publishError();
    if (!error) {
      return '';
    }
    if (error.detail) {
      return error.detail;
    }
    return this.i18n.text(error.kind === 'forbidden' ? 'knowledge.publishFailed.forbidden' : 'knowledge.publishFailed.generic');
  }

  extractErrorText(): string {
    return this.extractError()?.detail ?? this.i18n.text('knowledge.extractFailed.body');
  }

  // ---- Published ------------------------------------------------------------------------------------------------

  locationText(result: KnowledgePublishResult): string {
    return `${result.location.siteName} / ${result.location.libraryName} / ${result.location.folder}`;
  }

  sharePointUrl(result: KnowledgePublishResult): string | null {
    return safeHttpUrl(result.location.webUrl);
  }

  stepState(step: (typeof INDEX_STEPS)[number]): 'done' | 'active' | 'pending' | 'blocked' {
    const status = this.indexing();
    return status ? indexStepState(status.stage, step) : 'pending';
  }

  stageLabel(stage: string): string {
    return this.i18n.text(`knowledge.indexing.${stage}`);
  }

  skippedText(result: KnowledgePublishResult): string {
    return this.i18n.text('knowledge.success.skipped', { columns: result.skippedFields.join(', ') });
  }

  private pollIndexing(): void {
    const result = this.result();
    if (!result || this.polls >= MAX_POLLS) {
      return;
    }
    this.polls += 1;
    this.api.knowledgeIndexing(result).subscribe({
      next: (status) => this.indexing.set(status),
      error: () => this.indexing.update((status) => (status ? { ...status, stage: 'failed', message: this.i18n.text('knowledge.indexing.statusFailed') } : status)),
    });
  }

  refreshIndex(): void {
    const result = this.result();
    if (!result || this.refreshing()) {
      return;
    }
    this.refreshing.set(true);
    this.api.knowledgeIndexing(result, true).subscribe({
      next: (status) => {
        this.indexing.set(status);
        this.refreshing.set(false);
      },
      error: (error: unknown) => {
        const apiError = toApiError(error);
        this.indexing.update((status) => (status ? { ...status, stage: 'failed', message: apiError.detail ?? status.message } : status));
        this.refreshing.set(false);
      },
    });
  }

  askPrompt(): string {
    const result = this.result();
    const demoQuery = this.settingsData()?.demo.query ?? '';
    if (this.usedDemoConversation() && demoQuery) {
      return demoQuery;
    }
    return result ? `What does the knowledge document "${result.title}" recommend and why?` : demoQuery;
  }

  askAi(): void {
    void this.router.navigate([this.navigation.routeFor('agent')], { queryParams: { prompt: this.askPrompt() } });
  }

  downloadDemoDocument(): void {
    const result = this.result();
    if (!result) {
      return;
    }
    this.api.knowledgeDocument(result.artifactId).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const anchor = this.document.createElement('a');
        anchor.href = url;
        anchor.download = result.fileName;
        anchor.click();
        URL.revokeObjectURL(url);
      },
      error: () => undefined,
    });
  }

  captureAnother(): void {
    this.result.set(null);
    this.indexing.set(null);
    this.selectedIds.set([]);
    this.backToSelection();
  }

  retry(): void {
    this.session.refresh();
    this.settings.reload();
  }

  currentStepIndex(): number {
    switch (this.step()) {
      case 'review':
        return 1;
      case 'done':
        return 3;
      default:
        return 0;
    }
  }

  stepKeys = ['select', 'review', 'publish', 'ask'] as const;

  stepClass(index: number): string {
    const current = this.currentStepIndex();
    return index < current || (this.step() === 'done' && index <= 2) ? 'is-done' : index === current ? 'is-current' : '';
  }
}
