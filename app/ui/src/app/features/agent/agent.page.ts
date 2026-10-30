import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { IonContent, IonIcon, IonInput, IonTextarea } from '@ionic/angular';
import { ApiError, asApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { AgentPrompt, AgentPromptsResponse, AgentReply, EvidenceValue } from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService, lookupString } from '../../core/i18n/i18n.service';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { MarkdownComponent } from '../../shared/components/markdown/markdown.component';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { DisplayService } from '../../shared/util/display.service';
import { exportToExcel, exportToWord, exportToPpt } from '../../shared/util/export-doc';
import { safeHttpUrl } from '../../shared/util/url';

interface ChatMessage {
  id: number;
  role: 'user' | 'assistant' | 'error';
  text: string;
  reply: AgentReply | null;
  retryText: string | null;
  errorView: ViewState | null;
}

interface PromptGroup {
  issueId: string;
  issueLabel: string;
  prompts: AgentPrompt[];
}

/** Foundry agent: prompts grouped by issue (tap to send), placeholder inputs, transcript, and the message composer. */
@Component({
  selector: 'app-agent-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonInput, IonTextarea, BadgeComponent, MarkdownComponent, StateViewComponent, TranslatePipe],
  templateUrl: './agent.page.html',
  styleUrl: './agent.page.scss',
  host: { class: 'ion-page' },
})
export class AgentPage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  private readonly document = inject(DOCUMENT);
  readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;
  readonly foundryIconPath = this.config.theme.foundryIconPath;
  readonly maxInputChars = this.config.agent.maxInputChars;
  private readonly placeholderPattern = this.config.agent.placeholderPattern;
  readonly copiedMessageId = signal<number | null>(null);

  readonly prompts = rxResource({
    params: () => (this.session.gate() === 'ready' ? this.api.siteContext() ?? '__default__' : undefined),
    stream: () => this.api.agentPrompts(),
  });
  private readonly promptData = computed(() => this.prompts.hasValue() ? this.prompts.value() : undefined);
  readonly promptView = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.prompts.isLoading(),
      error: asApiError(this.prompts.error()),
      empty: (this.promptData()?.prompts.length ?? 0) === 0,
    }),
  );
  readonly groups = computed<PromptGroup[]>(() => groupByIssue(this.promptData()?.prompts ?? []));
  readonly placeholders = computed<string[]>(() => {
    const fromApi = this.promptData()?.placeholders;
    if (fromApi && fromApi.length > 0) {
      return fromApi;
    }
    const names = new Set<string>();
    for (const prompt of this.promptData()?.prompts ?? []) {
      placeholdersIn(prompt.text, this.placeholderPattern).forEach((name) => names.add(name));
    }
    return [...names];
  });

  readonly values = signal<Record<string, string>>({});
  readonly promptHint = signal<string | null>(null);

  readonly messages = signal<ChatMessage[]>([]);
  readonly draft = signal('');
  readonly sending = signal(false);
  readonly characterCount = computed(() =>
    this.i18n.text('agent.characterCount', { count: this.i18n.number(this.draft().length), max: this.i18n.number(this.maxInputChars) }),
  );
  readonly canSend = computed(() => !this.sending() && this.draft().trim().length > 0 && this.draft().length <= this.maxInputChars);
  private nextMessageId = 1;
  private readonly stageIndex = signal(0);
  private readonly stageKeys = ['agent.stages.routing', 'agent.stages.evidence', 'agent.stages.foundry', 'agent.stages.composing'];
  readonly stageLabel = computed(() => this.i18n.text(this.stageKeys[Math.min(this.stageIndex(), this.stageKeys.length - 1)]));

  constructor() {
    effect(() => {
      this.api.siteContext();
      untracked(() => {
        this.prompts.reload();
      });
    });
    effect((onCleanup) => {
      if (!this.sending()) {
        return;
      }
      untracked(() => this.stageIndex.set(0));
      const timer = globalThis.setInterval(() => this.stageIndex.update((index) => index + 1), 4000);
      onCleanup(() => globalThis.clearInterval(timer));
    });
  }

  onDraftInput(value: string | null | undefined): void {
    this.draft.set((value ?? '').slice(0, this.maxInputChars));
  }

  onPlaceholderInput(name: string, value: string | null | undefined): void {
    this.values.update((current) => ({ ...current, [name]: value ?? '' }));
  }

  placeholderValue(name: string): string {
    const typed = this.values()[name];
    if (typed !== undefined) {
      return typed;
    }
    if (name === 'userUpn') {
      return this.session.auth.account()?.username ?? '';
    }
    if (name === 'siteId') {
      return this.api.siteContext() ?? '';
    }
    return '';
  }

  placeholderLabel(name: string): string {
    return lookupString(this.config.strings, `agent.placeholderNames.${name}`) ?? this.i18n.text('agent.placeholderLabel', { name });
  }

  promptReady(prompt: AgentPrompt): boolean {
    return placeholdersIn(prompt.text, this.placeholderPattern).every((name) => this.placeholderValue(name).trim() !== '');
  }

  /** Tapping a prompt fills its placeholders and sends it. Missing values are reported instead. */
  usePrompt(prompt: AgentPrompt): void {
    const missing = placeholdersIn(prompt.text, this.placeholderPattern).find((name) => this.placeholderValue(name).trim() === '');
    if (missing !== undefined) {
      this.promptHint.set(this.i18n.text('agent.placeholderRequired', { name: missing }));
      return;
    }
    this.promptHint.set(null);
    const resolvedValues: Record<string, string> = { ...this.values() };
    for (const name of this.placeholders()) {
      if (resolvedValues[name] === undefined || resolvedValues[name].trim() === '') {
        resolvedValues[name] = this.placeholderValue(name);
      }
    }
    this.send(fillPlaceholders(prompt.text, resolvedValues, this.placeholderPattern));
  }

  sendDraft(): void {
    if (!this.canSend()) {
      return;
    }
    const text = this.draft();
    this.draft.set('');
    this.send(text);
  }

  retryMessage(message: ChatMessage): void {
    if (message.retryText) {
      this.send(message.retryText);
    }
  }

  send(text: string): void {
    const trimmed = text.trim();
    if (!trimmed || this.sending() || trimmed.length > this.maxInputChars) {
      return;
    }
    this.append({ role: 'user', text: trimmed, reply: null, retryText: null, errorView: null });
    this.sending.set(true);
    this.api.agentMessage(trimmed).subscribe({
      next: (reply) => {
        this.append({ role: 'assistant', text: reply.answer, reply, retryText: null, errorView: null });
        this.sending.set(false);
      },
      error: (error: unknown) => {
        const apiError: ApiError = toApiError(error);
        this.append({
          role: 'error',
          text: '',
          reply: null,
          retryText: trimmed,
          errorView: { kind: 'error', gate: null, errorKind: apiError.kind },
        });
        this.sending.set(false);
      },
    });
  }

  authorLabel(message: ChatMessage): string {
    return this.i18n.text(message.role === 'user' ? 'agent.you' : 'agent.assistant');
  }

  cellText(value: EvidenceValue): string {
    if (value === null) {
      return this.i18n.text('states.notAvailable');
    }
    if (typeof value === 'boolean') {
      return this.i18n.text(value ? 'document.yes' : 'document.no');
    }
    return typeof value === 'number' ? this.i18n.number(value) : value;
  }

  citationLink(url: string): string | null {
    return safeHttpUrl(url);
  }

  modeBadge(reply: AgentReply): { text: string; color: string } | null {
    return reply.mode === 'dryRun' ? { text: this.i18n.text('modeBadges.dryRun'), color: this.display.statusColor('dryRun') } : null;
  }

  retryPrompts(): void {
    this.session.refresh();
    this.prompts.reload();
  }

  exportExcel(message: ChatMessage): void {
    if (!message.reply) return;
    const evidence = message.reply.evidence;
    const headers = evidence?.columns ?? ['Summary'];
    const rows = evidence?.rows ?? [[message.reply.answer]];
    const title = `Agent Reply - ${message.reply.intent ?? 'Governance'}`;
    exportToExcel(
      this.document,
      `governance-agent-${message.reply.intent ?? 'export'}`,
      title,
      headers,
      rows,
      message.reply.facts as Record<string, unknown> | undefined,
    );
  }

  exportWord(message: ChatMessage): void {
    if (!message.reply) return;
    const title = `SharePoint Governance Agent - ${message.reply.intent ?? 'Analysis'}`;
    exportToWord(
      this.document,
      `governance-agent-${message.reply.intent ?? 'export'}`,
      title,
      message.reply.answer,
      message.reply.citations,
      message.reply.evidence,
    );
  }

  exportPpt(message: ChatMessage): void {
    if (!message.reply) return;
    const title = `Governance Insights - ${message.reply.intent ?? 'Summary'}`;
    exportToPpt(
      this.document,
      `governance-agent-${message.reply.intent ?? 'export'}`,
      title,
      message.reply.answer,
      message.reply.citations,
      message.reply.facts as Record<string, unknown> | undefined,
    );
  }

  async copyAnswer(message: ChatMessage): Promise<void> {
    if (!message.reply) return;
    try {
      await navigator.clipboard.writeText(message.reply.answer);
      this.copiedMessageId.set(message.id);
      setTimeout(() => {
        if (this.copiedMessageId() === message.id) {
          this.copiedMessageId.set(null);
        }
      }, 2000);
    } catch {
      // fallback
    }
  }

  getChartBars(reply: AgentReply): { label: string; value: number; percent: number; color: string }[] {
    const bars: { label: string; value: number; color: string }[] = [];
    const facts = reply.facts;
    if (facts) {
      if (typeof facts['byType'] === 'object' && facts['byType'] !== null) {
        for (const [key, val] of Object.entries(facts['byType'] as Record<string, number>)) {
          if (typeof val === 'number' && val > 0) {
            bars.push({ label: this.formatChartLabel(key), value: val, color: this.chartColor(key) });
          }
        }
      }
      if (typeof facts['byGrantedVia'] === 'object' && facts['byGrantedVia'] !== null) {
        for (const [key, val] of Object.entries(facts['byGrantedVia'] as Record<string, number>)) {
          if (typeof val === 'number' && val > 0) {
            bars.push({ label: this.formatChartLabel(key), value: val, color: this.chartColor(key) });
          }
        }
      }
      if (typeof facts['expired'] === 'number' || typeof facts['reviewOverdue'] === 'number') {
        if ((facts['expired'] as number) > 0) {
          bars.push({ label: 'Expired', value: facts['expired'] as number, color: '#D13438' });
        }
        if ((facts['reviewOverdue'] as number) > 0) {
          bars.push({ label: 'Review Overdue', value: facts['reviewOverdue'] as number, color: '#FF8C00' });
        }
      }
      if (typeof facts['drafted'] === 'number') {
        if ((facts['drafted'] as number) > 0) {
          bars.push({ label: 'Drafted Notifications', value: facts['drafted'] as number, color: '#107C41' });
        }
      }
    }

    if (bars.length === 0) {
      return [];
    }
    const max = Math.max(...bars.map((b) => b.value), 1);
    return bars.map((b) => ({ ...b, percent: Math.max(8, Math.round((b.value / max) * 100)) }));
  }

  private formatChartLabel(key: string): string {
    return key.replace(/([A-Z])/g, ' $1').replace(/^./, (str) => str.toUpperCase());
  }

  private chartColor(key: string): string {
    const k = key.toLowerCase();
    if (k.includes('critical') || k.includes('everyone') || k.includes('anonymous')) return '#D13438';
    if (k.includes('high') || k.includes('warning') || k.includes('direct')) return '#FF8C00';
    if (k.includes('medium') || k.includes('group')) return '#0078D4';
    if (k.includes('good') || k.includes('success')) return '#107C41';
    return '#5C2D91';
  }

  private append(message: Omit<ChatMessage, 'id'>): void {
    const id = this.nextMessageId++;
    this.messages.update((current) => [...current, { id, ...message }]);
  }
}

/** Placeholder names in a prompt, in order of first appearance. */
export function placeholdersIn(text: string, pattern: string): string[] {
  const names: string[] = [];
  for (const match of text.matchAll(new RegExp(pattern, 'g'))) {
    if (match[1] && !names.includes(match[1])) {
      names.push(match[1]);
    }
  }
  return names;
}

export function fillPlaceholders(text: string, values: Record<string, string>, pattern: string): string {
  return text.replace(new RegExp(pattern, 'g'), (token: string, name: string) => (values[name] ?? '').trim() || token);
}

/** Groups prompts by issueId, keeping the order in which issues first appear. The label comes from the prompt file. */
export function groupByIssue(prompts: AgentPrompt[]): PromptGroup[] {
  const groups = new Map<string, PromptGroup>();
  for (const prompt of prompts) {
    const group = groups.get(prompt.issueId) ?? { issueId: prompt.issueId, issueLabel: prompt.issueLabel, prompts: [] };
    group.prompts.push(prompt);
    groups.set(prompt.issueId, group);
  }
  return [...groups.values()];
}
