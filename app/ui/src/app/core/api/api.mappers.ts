import {
  AgentEvidence,
  AgentMessageResponse,
  AgentReply,
  AnomaliesResponse,
  AnomalyRecord,
  CleanupDraftTemplates,
  CleanupRecord,
  DocumentRef,
  DuplicateClusterRecord,
  DuplicatesResponse,
  ClusterMember,
  EvidenceValue,
  ExposureRecord,
  ExposureResponse,
  ExpiryRecord,
  ExpiryResponse,
  Page,
} from './models/api.models';

/** Routes that page by number turn into cursor pages: the cursor is the number of the next page. */
export function cursorPage<T>(response: { items: T[]; page: number; totalPages: number }): Page<T> {
  return {
    items: response.items,
    nextCursor: response.page < response.totalPages ? String(response.page + 1) : null,
  };
}

/** Routes that do not page return one page with no cursor. */
export function unpaged<T>(items: T[]): Page<T> {
  return { items, nextCursor: null };
}

export function documentRef(item: DocumentRef): DocumentRef {
  return { id: item.id, name: item.name, path: item.path, webUrl: item.webUrl };
}

/** Exact and near clusters become one record list. The canonical copy is the member marked canonical. */
export function duplicateRecords(response: DuplicatesResponse): DuplicateClusterRecord[] {
  return [...response.exact, ...response.near].map((cluster): DuplicateClusterRecord => {
    const members: ClusterMember[] = cluster.members.map((member) => ({ ...documentRef(member), role: member.role }));
    const canonical: DocumentRef = members.find((member) => member.role === 'canonical') ?? {
      id: cluster.canonical,
      name: cluster.canonical,
      path: null,
      webUrl: null,
    };
    return { segment: 'duplicates', id: cluster.clusterId, kind: cluster.kind, canonical, members };
  });
}

/** Expired documents first. A document that is expired is not listed again as review-overdue. */
export function expiryRecords(response: ExpiryResponse): ExpiryRecord[] {
  const expired = response.expired.map((doc): ExpiryRecord => ({
    segment: 'expiry',
    id: doc.id,
    document: documentRef(doc),
    reason: 'expired',
    date: doc.expiry.expirationDate,
    days: doc.expiry.daysPastExpiration,
  }));
  const expiredIds = new Set(response.expired.map((doc) => doc.id));
  const overdue = response.reviewOverdue
    .filter((doc) => !expiredIds.has(doc.id))
    .map((doc): ExpiryRecord => ({
      segment: 'expiry',
      id: doc.id,
      document: documentRef(doc),
      reason: 'reviewOverdue',
      date: doc.expiry.reviewDate,
      days: doc.expiry.daysOverdue,
    }));
  return [...expired, ...overdue];
}

export function anomalyRecords(response: AnomaliesResponse): AnomalyRecord[] {
  return response.items.map((row): AnomalyRecord => ({
    segment: 'anomalies',
    id: row.item.id,
    document: documentRef(row.item),
    score: row.score,
    contributions: row.topContributions.map((entry) => ({ feature: entry.feature, contribution: entry.share })),
  }));
}

export function exposureRecords(response: ExposureResponse): ExposureRecord[] {
  return response.findings.map((finding): ExposureRecord => ({
    segment: 'exposure',
    id: finding.id,
    document: documentRef(finding.subject),
    exposure: finding.type,
    severity: finding.severity,
    detail: finding.detail,
  }));
}

/** Template for drafting a notification about one document in a cleanup record, or null when it cannot be drafted. */
export function draftTemplateId(
  record: CleanupRecord,
  documentId: string,
  templates: CleanupDraftTemplates,
): string | null {
  switch (record.segment) {
    case 'duplicates': {
      const member = record.members.find((candidate) => candidate.id === documentId);
      if (member?.role !== 'duplicate') {
        return null;
      }
      return record.kind === 'exact' ? templates.exact : templates.near;
    }
    case 'expiry':
      if (record.document.id !== documentId) {
        return null;
      }
      return record.reason === 'expired' ? templates.expired : templates.reviewOverdue;
    default:
      return null;
  }
}

/** The evidence rows of an agent reply: columns are the keys of the rows, in first-seen order. */
export function evidenceTable(items: Record<string, unknown>[] | undefined): AgentEvidence {
  const rows = items ?? [];
  const columns: string[] = [];
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!columns.includes(key)) {
        columns.push(key);
      }
    }
  }
  return { columns, rows: rows.map((row) => columns.map((column) => evidenceValue(row[column]))) };
}

export function evidenceValue(value: unknown): EvidenceValue {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value;
  }
  if (Array.isArray(value) && value.every((entry) => typeof entry === 'string' || typeof entry === 'number')) {
    return value.join(', ');
  }
  return JSON.stringify(value);
}

export function agentReply(response: AgentMessageResponse): AgentReply {
  return {
    answer: response.answer,
    mode: response.mode,
    intent: response.intent,
    evidence: response.evidence ? evidenceTable(response.evidence.items) : null,
    citations: response.citations,
  };
}
