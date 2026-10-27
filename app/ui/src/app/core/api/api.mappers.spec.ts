import {
  AgentMessageResponse,
  AnomaliesResponse,
  CleanupDraftTemplates,
  DocumentSummary,
  DuplicatesResponse,
  ExpiryResponse,
  ExpiryView,
  ExposureResponse,
  ItemView,
} from './models/api.models';
import {
  agentReply,
  anomalyRecords,
  cursorPage,
  draftTemplateId,
  duplicateRecords,
  evidenceTable,
  evidenceValue,
  exposureRecords,
  expiryRecords,
  unpaged,
} from './api.mappers';

const TEMPLATES: CleanupDraftTemplates = {
  exact: 'exact-duplicates',
  near: 'near-duplicates',
  expired: 'expired-documents',
  reviewOverdue: 'requires-review',
};

function summary(overrides: Partial<DocumentSummary> & Pick<DocumentSummary, 'id' | 'name'>): DocumentSummary {
  return {
    libraryId: 'library-1',
    libraryTitle: 'Trusted Knowledge',
    kind: 'file',
    path: `/sites/knowledge/${overrides.name}`,
    webUrl: `https://contoso.sharepoint.com/${overrides.name}`,
    hasUniquePermissions: false,
    modified: null,
    title: overrides.name,
    size: 1024,
    artifactId: null,
    knowledgeCategory: 'Quality',
    lifecycleStatus: 'Published',
    authoritative: true,
    aiReady: true,
    reviewDate: null,
    expirationDate: null,
    effectiveDate: null,
    documentType: null,
    productFamily: null,
    processArea: null,
    sensitivity: null,
    dataQualityStatus: null,
    conflictStatus: null,
    trustScore: 80,
    knowledgeOwner: null,
    ownerDisplayName: null,
    duplicateOf: null,
    ...overrides,
  };
}

function expiryView(overrides: Partial<ExpiryView>): ExpiryView {
  return {
    expired: false,
    expiredBy: [],
    expirationDate: null,
    daysPastExpiration: null,
    reviewDate: null,
    reviewOverdue: false,
    overdueBy: [],
    daysOverdue: null,
    textDates: [],
    ...overrides,
  };
}

function itemView(id: string, name: string): ItemView {
  return {
    id,
    libraryId: 'library-1',
    libraryTitle: 'Trusted Knowledge',
    name,
    kind: 'file',
    path: `/sites/knowledge/${name}`,
    webUrl: null,
    hasUniquePermissions: false,
    modified: null,
  };
}

const DUPLICATES: DuplicatesResponse = {
  exact: [
    {
      clusterId: 'exact-1',
      libraryId: 'library-1',
      kind: 'exact',
      reason: 'Same content hash',
      canonical: 'd1',
      size: 2,
      members: [
        { ...summary({ id: 'd1', name: 'Master.docx' }), role: 'canonical' },
        { ...summary({ id: 'd2', name: 'Copy.docx' }), role: 'duplicate' },
      ],
    },
  ],
  near: [
    {
      clusterId: 'near-1',
      libraryId: 'library-1',
      kind: 'near',
      reason: 'Similar text',
      canonical: 'n1',
      size: 2,
      members: [
        { ...summary({ id: 'n1', name: 'Spec.docx' }), role: 'canonical' },
        { ...summary({ id: 'n2', name: 'Spec v2.docx' }), role: 'duplicate' },
      ],
    },
  ],
  asOfDate: '2026-10-21',
  libraries: [],
};

describe('api mappers', () => {
  describe('paging', () => {
    it('uses the number of the next page as the cursor until the last page', () => {
      expect(cursorPage({ items: ['a'], page: 1, totalPages: 2 })).toEqual({ items: ['a'], nextCursor: '2' });
      expect(cursorPage({ items: ['b'], page: 2, totalPages: 2 }).nextCursor).toBeNull();
    });

    it('returns unpaged lists without a cursor', () => {
      expect(unpaged([1, 2])).toEqual({ items: [1, 2], nextCursor: null });
    });
  });

  describe('duplicate clusters', () => {
    it('lists exact clusters before near clusters, with the canonical member and each member role', () => {
      const records = duplicateRecords(DUPLICATES);

      expect(records.map((record) => [record.id, record.kind])).toEqual([
        ['exact-1', 'exact'],
        ['near-1', 'near'],
      ]);
      expect(records[0].canonical.id).toBe('d1');
      expect(records[0].members.map((member) => [member.id, member.role])).toEqual([
        ['d1', 'canonical'],
        ['d2', 'duplicate'],
      ]);
    });

    it('drafts only duplicate copies, using the template for the cluster kind', () => {
      const [exact, near] = duplicateRecords(DUPLICATES);

      expect(draftTemplateId(exact, 'd2', TEMPLATES)).toBe('exact-duplicates');
      expect(draftTemplateId(exact, 'd1', TEMPLATES)).toBeNull();
      expect(draftTemplateId(near, 'n2', TEMPLATES)).toBe('near-duplicates');
      expect(draftTemplateId(near, 'unknown', TEMPLATES)).toBeNull();
    });
  });

  describe('expiry records', () => {
    it('lists expired documents, then review-overdue documents that are not already expired', () => {
      const response: ExpiryResponse = {
        asOfDate: '2026-10-21',
        reviewOverdueGraceDays: 30,
        libraries: [],
        expired: [
          {
            ...summary({ id: 'e1', name: 'Old.docx' }),
            expiry: expiryView({ expired: true, expirationDate: '2026-01-31', daysPastExpiration: 263 }),
          },
        ],
        reviewOverdue: [
          {
            ...summary({ id: 'e1', name: 'Old.docx' }),
            expiry: expiryView({ reviewOverdue: true, reviewDate: '2026-02-01', daysOverdue: 262 }),
          },
          {
            ...summary({ id: 'r1', name: 'Review.docx' }),
            expiry: expiryView({ reviewOverdue: true, reviewDate: '2026-03-01', daysOverdue: 234 }),
          },
        ],
      };

      const records = expiryRecords(response);

      expect(records.map((record) => [record.id, record.reason, record.date, record.days])).toEqual([
        ['e1', 'expired', '2026-01-31', 263],
        ['r1', 'reviewOverdue', '2026-03-01', 234],
      ]);
      expect(draftTemplateId(records[0], 'e1', TEMPLATES)).toBe('expired-documents');
      expect(draftTemplateId(records[1], 'r1', TEMPLATES)).toBe('requires-review');
    });
  });

  describe('anomaly and exposure records', () => {
    it('keeps the anomaly score and turns the top contributions into feature contributions', () => {
      const response: AnomaliesResponse = {
        asOfDate: '2026-10-21',
        libraries: [],
        items: [
          {
            item: itemView('a1', 'Spike.xlsx'),
            title: 'Spike',
            rank: 1,
            score: 0.71,
            isAnomaly: true,
            topContributions: [{ feature: 'size', share: 0.6 }],
          },
        ],
      };

      const [record] = anomalyRecords(response);

      expect(record.document.id).toBe('a1');
      expect(record.score).toBe(0.71);
      expect(record.contributions).toEqual([{ feature: 'size', contribution: 0.6 }]);
      expect(draftTemplateId(record, 'a1', TEMPLATES)).toBeNull();
    });

    it('shows each exposure finding with its type, severity and detail', () => {
      const response: ExposureResponse = {
        asOfDate: '2026-10-21',
        total: 1,
        bySeverity: { critical: 1 },
        libraries: [],
        findings: [
          {
            id: 'everyoneIncludingExternal:a1:everyone',
            type: 'everyoneIncludingExternal',
            severity: 'critical',
            subject: itemView('a1', 'Anonymous.docx'),
            principal: { type: 'claims', id: 'everyone', displayName: 'Everyone', loginName: null, email: null },
            role: 'Read',
            grantedVia: 'everyone',
            member: null,
            detail: 'Visible to everyone, including guests',
          },
        ],
      };

      const [record] = exposureRecords(response);

      expect(record.id).toBe('everyoneIncludingExternal:a1:everyone');
      expect(record.document.name).toBe('Anonymous.docx');
      expect(record.exposure).toBe('everyoneIncludingExternal');
      expect(record.severity).toBe('critical');
      expect(record.detail).toBe('Visible to everyone, including guests');
    });
  });

  describe('agent evidence', () => {
    it('builds columns from every row in first-seen order and aligns the cells', () => {
      const table = evidenceTable([
        { title: 'A', score: 0.5 },
        { title: 'B', owners: ['x@contoso.com', 'z@contoso.com'], current: true },
      ]);

      expect(table.columns).toEqual(['title', 'score', 'owners', 'current']);
      expect(table.rows).toEqual([
        ['A', 0.5, null, null],
        ['B', null, 'x@contoso.com, z@contoso.com', true],
      ]);
    });

    it('renders nested objects as JSON text', () => {
      expect(evidenceValue({ feature: 'size', share: 0.6 })).toBe('{"feature":"size","share":0.6}');
    });

    it('maps a reply to the answer, its citations and the evidence table', () => {
      const response: AgentMessageResponse = {
        conversationId: 'c1',
        answer: 'One duplicate pair was found.',
        mode: 'evidence',
        intent: 'duplicates',
        evidence: { items: [{ title: 'Copy.docx' }] },
        citations: [{ title: 'Copy.docx', url: 'https://contoso.sharepoint.com/Copy.docx' }],
        warnings: [],
      };

      expect(agentReply(response)).toEqual({
        answer: 'One duplicate pair was found.',
        mode: 'evidence',
        intent: 'duplicates',
        evidence: { columns: ['title'], rows: [['Copy.docx']] },
        citations: [{ title: 'Copy.docx', url: 'https://contoso.sharepoint.com/Copy.docx' }],
      });
    });

    it('returns no evidence table when the reply has no evidence', () => {
      const reply = agentReply({
        conversationId: 'c2',
        answer: 'No data.',
        mode: 'evidence',
        intent: null,
        evidence: null,
        citations: [],
        warnings: [],
      });

      expect(reply.evidence).toBeNull();
    });
  });
});
