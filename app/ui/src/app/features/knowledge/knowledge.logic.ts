import {
  KnowledgeDraft,
  KnowledgeIndexStage,
  KnowledgeOrigin,
  KnowledgePublishRequest,
} from '../../core/api/models/api.models';

/** The review form. Lists are edited as text: key facts one per line, tags comma separated. */
export interface KnowledgeForm {
  title: string;
  executiveSummary: string;
  category: string;
  issueContext: string;
  rootCause: string;
  decision: string;
  recommendedAction: string;
  keyFacts: string;
  department: string;
  product: string;
  ownerName: string;
  ownerUpn: string;
  sourceType: string;
  sourceDescription: string;
  sensitivity: string;
  reviewDate: string;
  tags: string;
}

export type KnowledgeFieldName = keyof KnowledgeForm;
export type KnowledgeErrorKey = 'title' | 'executiveSummary' | 'category' | 'owner' | 'sensitivity' | 'reviewDate' | 'content' | 'attestation';

export interface ReviewLimits {
  maxMonths: number;
}

export const OWNER_EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
export const INDEX_STEPS: KnowledgeIndexStage[] = ['published', 'indexing', 'available'];
export const TERMINAL_STAGES: KnowledgeIndexStage[] = ['available', 'failed', 'notReady', 'delayed'];
export const MIN_TITLE_LENGTH = 5;

/** Selecting a message that is already selected removes it. The order of selection is kept. */
export function toggleSelection(selected: string[], id: string): string[] {
  return selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id];
}

export function splitLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

export function splitTags(text: string): string[] {
  return [...new Set(text.split(/[;,]/).map((tag) => tag.trim()).filter((tag) => tag.length > 0))];
}

export function formFromDraft(draft: KnowledgeDraft): KnowledgeForm {
  return {
    title: draft.title,
    executiveSummary: draft.executiveSummary,
    category: draft.category,
    issueContext: draft.issueContext,
    rootCause: draft.rootCause,
    decision: draft.decision,
    recommendedAction: draft.recommendedAction,
    keyFacts: draft.keyFacts.join('\n'),
    department: draft.department,
    product: draft.product,
    ownerName: draft.ownerName,
    ownerUpn: draft.ownerUpn,
    sourceType: draft.sourceType,
    sourceDescription: draft.sourceDescription,
    sensitivity: draft.sensitivity,
    reviewDate: draft.reviewDate,
    tags: draft.tags.join(', '),
  };
}

/** The origin of a form field. Origins an edit has touched become 'source': the user now stands behind the value. */
export function originOf(draft: KnowledgeDraft | null, field: string, edited: ReadonlySet<string>): KnowledgeOrigin | null {
  if (!draft) {
    return null;
  }
  const origin: KnowledgeOrigin = draft.origins[field] ?? 'unknown';
  if (edited.has(field) && (origin === 'unknown' || origin === 'default')) {
    return 'source';
  }
  return origin;
}

function addMonths(from: Date, months: number): Date {
  const result = new Date(from.getFullYear(), from.getMonth() + months, from.getDate());
  return result;
}

function isoDay(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${value.getFullYear()}-${month}-${day}`;
}

/** Mirrors the API's validation so most problems are shown before the request is sent. The API remains the authority. */
export function validateForm(form: KnowledgeForm, limits: ReviewLimits, attested: boolean, sensitivities: string[], categories: string[], today: Date = new Date()): KnowledgeErrorKey[] {
  const errors: KnowledgeErrorKey[] = [];
  if (form.title.trim().length < MIN_TITLE_LENGTH) {
    errors.push('title');
  }
  if (form.executiveSummary.trim().length === 0) {
    errors.push('executiveSummary');
  }
  if (!categories.includes(form.category)) {
    errors.push('category');
  }
  if (!OWNER_EMAIL.test(form.ownerUpn.trim())) {
    errors.push('owner');
  }
  if (!sensitivities.includes(form.sensitivity)) {
    errors.push('sensitivity');
  }
  const todayIso = isoDay(today);
  const maxIso = isoDay(addMonths(today, limits.maxMonths));
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.reviewDate) || form.reviewDate <= todayIso || form.reviewDate > maxIso) {
    errors.push('reviewDate');
  }
  if (!form.decision.trim() && !form.rootCause.trim() && !form.recommendedAction.trim()) {
    errors.push('content');
  }
  if (!attested) {
    errors.push('attestation');
  }
  return errors;
}

export function buildPublishRequest(
  form: KnowledgeForm,
  meta: { confidence: number; provider: string; selectedMessageCount: number; authoritative: boolean; attested: boolean },
): KnowledgePublishRequest {
  return {
    title: form.title.trim(),
    executiveSummary: form.executiveSummary.trim(),
    category: form.category,
    issueContext: form.issueContext.trim(),
    rootCause: form.rootCause.trim(),
    decision: form.decision.trim(),
    recommendedAction: form.recommendedAction.trim(),
    keyFacts: splitLines(form.keyFacts),
    department: form.department.trim(),
    product: form.product.trim(),
    ownerName: form.ownerName.trim(),
    ownerUpn: form.ownerUpn.trim(),
    sourceType: form.sourceType.trim(),
    sourceDescription: form.sourceDescription.trim(),
    sensitivity: form.sensitivity,
    reviewDate: form.reviewDate,
    tags: splitTags(form.tags),
    confidence: meta.confidence,
    extractionProvider: meta.provider,
    selectedMessageCount: meta.selectedMessageCount,
    authoritative: meta.authoritative,
    attested: meta.attested,
  };
}

/** Where a stage sits in Published > Indexing > Available. Not-ready, delayed and failed stop after the stage they reached. */
export function indexStepState(stage: KnowledgeIndexStage, step: KnowledgeIndexStage): 'done' | 'active' | 'pending' | 'blocked' {
  if (stage === 'notReady') {
    return step === 'published' ? 'done' : 'blocked';
  }
  const reached = stage === 'delayed' || stage === 'failed' ? 'indexing' : stage;
  const position = INDEX_STEPS.indexOf(reached);
  const target = INDEX_STEPS.indexOf(step);
  if (stage === 'available') {
    return 'done';
  }
  if (target < position) {
    return 'done';
  }
  if (target === position) {
    return stage === 'failed' || stage === 'delayed' ? 'blocked' : 'active';
  }
  return 'pending';
}

export function isTerminalStage(stage: KnowledgeIndexStage): boolean {
  return TERMINAL_STAGES.includes(stage);
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter((part) => part.length > 0);
  return parts.length === 0 ? '?' : (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}
