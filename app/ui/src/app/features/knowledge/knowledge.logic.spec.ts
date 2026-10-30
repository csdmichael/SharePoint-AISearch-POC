import { KnowledgeDraft } from '../../core/api/models/api.models';
import {
  KnowledgeForm,
  buildPublishRequest,
  formFromDraft,
  indexStepState,
  initials,
  isTerminalStage,
  originOf,
  splitLines,
  splitTags,
  toggleSelection,
  validateForm,
} from './knowledge.logic';

const draft: KnowledgeDraft = {
  title: 'Firmware 4.8.2 Adaptive Polling Workaround',
  executiveSummary: 'Disable adaptive polling until 4.8.3.',
  category: 'Troubleshooting',
  issueContext: 'Qualification failed.',
  rootCause: 'Firmware 4.8.2.',
  decision: '',
  recommendedAction: 'Disable adaptive polling.',
  keyFacts: ['Affected: 4.8.2', 'Fixed in 4.8.3'],
  department: 'Engineering',
  product: 'ApexDrive X500',
  ownerName: 'Test Auditor',
  ownerUpn: 'auditor@contoso.com',
  ownerMention: '',
  sourceType: 'Teams Collaboration',
  sourceDescription: 'Teams chat',
  sensitivity: 'General',
  reviewDate: '2027-04-30',
  tags: ['firmware', 'polling'],
  confidence: 0.86,
  status: 'Draft',
  origins: { title: 'ai', rootCause: 'source', decision: 'unknown', owner: 'default' },
};
const today = new Date(2026, 9, 30);
const sensitivities = ['General', 'Confidential'];
const categories = ['Troubleshooting', 'Decision'];

function validate(form: KnowledgeForm, attested = true) {
  return validateForm(form, { maxMonths: 36 }, attested, sensitivities, categories, today);
}

describe('Knowledge Capture logic', () => {
  describe('selection', () => {
    it('adds a message and removes it again, keeping the order of selection', () => {
      expect(toggleSelection([], 'm2')).toEqual(['m2']);
      expect(toggleSelection(['m2'], 'm1')).toEqual(['m2', 'm1']);
      expect(toggleSelection(['m2', 'm1'], 'm2')).toEqual(['m1']);
    });
  });

  describe('text lists', () => {
    it('splits key facts by line and ignores blanks', () => {
      expect(splitLines('One\r\n\n  Two  \n')).toEqual(['One', 'Two']);
    });

    it('splits tags by comma or semicolon and removes duplicates', () => {
      expect(splitTags('a, b;a ,, c')).toEqual(['a', 'b', 'c']);
    });
  });

  describe('form', () => {
    it('turns a draft into editable text and back into a trimmed publish request', () => {
      const form = formFromDraft(draft);
      expect(form.keyFacts).toBe('Affected: 4.8.2\nFixed in 4.8.3');
      expect(form.tags).toBe('firmware, polling');
      const request = buildPublishRequest({ ...form, title: '  Edited title  ', keyFacts: 'A\n\nB' }, {
        confidence: 0.5,
        provider: 'foundry',
        selectedMessageCount: 2,
        authoritative: true,
        attested: true,
      });
      expect(request.title).toBe('Edited title');
      expect(request.keyFacts).toEqual(['A', 'B']);
      expect(request.tags).toEqual(['firmware', 'polling']);
      expect(request.extractionProvider).toBe('foundry');
      expect(request.attested).toBe(true);
    });
  });

  describe('validation', () => {
    const form = formFromDraft(draft);

    it('accepts a complete reviewed draft', () => {
      expect(validate(form)).toEqual([]);
    });

    it('requires the confirmation before publishing', () => {
      expect(validate(form, false)).toEqual(['attestation']);
    });

    it('flags each invalid field', () => {
      const broken: KnowledgeForm = {
        ...form,
        title: 'abc',
        executiveSummary: ' ',
        category: 'Gossip',
        ownerUpn: 'nobody',
        sensitivity: 'Secret',
        reviewDate: '2026-10-30',
        recommendedAction: '',
        rootCause: '',
        decision: '',
      };
      expect(validate(broken)).toEqual(['title', 'executiveSummary', 'category', 'owner', 'sensitivity', 'reviewDate', 'content']);
    });

    it('rejects a review date beyond the allowed window', () => {
      expect(validate({ ...form, reviewDate: '2030-01-01' })).toEqual(['reviewDate']);
      expect(validate({ ...form, reviewDate: '2029-10-30' })).toEqual([]);
      expect(validate({ ...form, reviewDate: 'soon' })).toEqual(['reviewDate']);
    });
  });

  describe('origin chips', () => {
    it('reports the origin of the draft and promotes missing values the user completed', () => {
      expect(originOf(draft, 'rootCause', new Set())).toBe('source');
      expect(originOf(draft, 'decision', new Set())).toBe('unknown');
      expect(originOf(draft, 'decision', new Set(['decision']))).toBe('source');
      expect(originOf(draft, 'owner', new Set(['owner']))).toBe('source');
      expect(originOf(draft, 'title', new Set(['title']))).toBe('ai');
      expect(originOf(null, 'title', new Set())).toBeNull();
    });
  });

  describe('indexing tracker', () => {
    it('moves from published to available', () => {
      expect(indexStepState('published', 'published')).toBe('active');
      expect(indexStepState('published', 'indexing')).toBe('pending');
      expect(indexStepState('indexing', 'published')).toBe('done');
      expect(indexStepState('indexing', 'indexing')).toBe('active');
      expect(indexStepState('available', 'available')).toBe('done');
    });

    it('stops at the stage that failed, delayed or is not AI-ready', () => {
      expect(indexStepState('failed', 'indexing')).toBe('blocked');
      expect(indexStepState('delayed', 'available')).toBe('pending');
      expect(indexStepState('notReady', 'published')).toBe('done');
      expect(indexStepState('notReady', 'indexing')).toBe('blocked');
    });

    it('stops polling at a terminal stage', () => {
      expect(isTerminalStage('available')).toBe(true);
      expect(isTerminalStage('failed')).toBe(true);
      expect(isTerminalStage('indexing')).toBe(false);
      expect(isTerminalStage('published')).toBe(false);
    });
  });

  it('builds avatar initials', () => {
    expect(initials('Priya Raman')).toBe('PR');
    expect(initials('Daniel')).toBe('D');
    expect(initials('  ')).toBe('?');
  });
});
