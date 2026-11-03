import { DocumentPreview, DocumentPreviewBlock } from '../../core/api/models/api.models';
import { changeKey, diffDocumentPreviews, previewPages } from './document-diff';

function docx(pages: { title: string; blocks: DocumentPreviewBlock[] }[]): DocumentPreview {
  return {
    kind: 'docx',
    name: 'test.docx',
    pageCount: pages.length,
    pages: pages.map((page, index) => ({ number: index + 1, title: page.title, blocks: page.blocks })),
    blocks: [],
    tables: [],
  };
}

describe('diffDocumentPreviews', () => {
  it('reports nothing for spacing-only differences', () => {
    const { left, right } = diffDocumentPreviews(
      docx([{ title: 'Intro', blocks: [{ kind: 'paragraph', text: 'Leave  policy' }] }]),
      docx([{ title: 'Intro', blocks: [{ kind: 'paragraph', text: ' Leave policy ' }] }]),
    );
    expect(left).toEqual({ units: new Set(), rows: new Set() });
    expect(right).toEqual({ units: new Set(), rows: new Set() });
  });

  it('marks the edited row and its page on both sides', () => {
    const introPage = { title: 'Intro', blocks: [] };
    const termsPage = (weeks: string) => ({
      title: 'Terms',
      blocks: [
        { kind: 'heading' as const, text: 'Terms' },
        { kind: 'paragraph' as const, text: `Retention is ${weeks} weeks` },
        { kind: 'paragraph' as const, text: 'Same' },
      ],
    });
    const { left, right } = diffDocumentPreviews(docx([introPage, termsPage('12')]), docx([introPage, termsPage('16')]));
    expect(left).toEqual({ units: new Set([2]), rows: new Set([changeKey(2, 1)]) });
    expect(right).toEqual({ units: new Set([2]), rows: new Set([changeKey(2, 1)]) });
  });

  it('reports only an inserted row, not the rows around it', () => {
    const paragraphs = (...texts: string[]) =>
      docx([{ title: 'Body', blocks: texts.map((text) => ({ kind: 'paragraph' as const, text })) }]);
    const { left, right } = diffDocumentPreviews(paragraphs('A', 'B', 'C'), paragraphs('A', 'X', 'B', 'C'));
    expect(left).toEqual({ units: new Set(), rows: new Set() });
    expect(right).toEqual({ units: new Set([1]), rows: new Set([changeKey(1, 1)]) });
  });

  it('reports a table row only when its cells change', () => {
    const controls = (status: string) =>
      docx([{ title: 'Controls', blocks: [{ kind: 'table', table: [['Control', 'Status'], ['CTRL-1', 'Verified'], ['CTRL-2', status]] }] }]);
    const { left, right } = diffDocumentPreviews(controls('Verified'), controls('Pending'));
    expect(left.rows).toEqual(new Set([changeKey(1, 0, 2)]));
    expect(right.rows).toEqual(new Set([changeKey(1, 0, 2)]));
  });

  it('reports pages that exist on only one side', () => {
    const { left, right } = diffDocumentPreviews(
      docx([{ title: 'Intro', blocks: [] }]),
      docx([{ title: 'Intro', blocks: [] }, { title: 'Appendix', blocks: [{ kind: 'paragraph', text: 'Notes' }] }]),
    );
    expect(left).toEqual({ units: new Set(), rows: new Set() });
    expect(right).toEqual({ units: new Set([2]), rows: new Set([changeKey(2, 'title'), changeKey(2, 0)]) });
  });

  it('reports a changed slide title', () => {
    const deck = (title: string): DocumentPreview => ({
      kind: 'pptx',
      name: 'deck.pptx',
      pageCount: 1,
      slides: [{ number: 1, title, blocks: [{ lines: ['Eighteen managers'] }] }],
    });
    const { left, right } = diffDocumentPreviews(deck('Cohort overview'), deck('Cohort summary'));
    expect(left.rows).toEqual(new Set([changeKey(1, 'title')]));
    expect(right.rows).toEqual(new Set([changeKey(1, 'title')]));
  });

  it('compares xlsx sheets by cell and by embedded image', () => {
    const workbook = (premium: string, image: string): DocumentPreview => ({
      kind: 'xlsx',
      name: 'plans.xlsx',
      pageCount: 1,
      sheets: [{ name: 'Plans', rows: [['Plan', 'Premium'], ['PPO', premium]], images: [image] }],
    });
    const { left, right } = diffDocumentPreviews(
      workbook('145', 'data:image/png;base64,AAAA'),
      workbook('150', 'data:image/png;base64,BBBB'),
    );
    expect(left.rows).toEqual(new Set([changeKey(1, 0, 1), changeKey(1, 1)]));
    expect(right.rows).toEqual(new Set([changeKey(1, 0, 1), changeKey(1, 1)]));
  });

  it('matches identical rows by content when a unit is too large to align', () => {
    const rows = (order: number[]) =>
      docx([{ title: 'Big', blocks: order.map((n) => ({ kind: 'paragraph' as const, text: `Row ${n}` })) }]);
    const ascending = Array.from({ length: 1001 }, (_, index) => index);
    const { left, right } = diffDocumentPreviews(rows(ascending), rows([...ascending].reverse()));
    expect(left.rows.size).toBe(0);
    expect(right.rows.size).toBe(0);
  });
});

describe('previewPages', () => {
  it('shows a docx without page breaks as one page built from its blocks and tables', () => {
    const pages = previewPages({
      kind: 'docx',
      name: 'a.docx',
      blocks: [{ kind: 'paragraph', text: 'Intro' }],
      tables: [[['Plan']]],
    });
    expect(pages.map((page) => page.number)).toEqual([1]);
    expect(pages[0].blocks.map((block) => block.kind)).toEqual(['paragraph', 'table']);
  });
});
