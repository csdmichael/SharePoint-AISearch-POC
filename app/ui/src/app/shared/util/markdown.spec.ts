import { parseInline, parseMarkdown } from './markdown';

describe('markdown parser', () => {
  it('parses headings, bold text, bullets and a table', () => {
    const blocks = parseMarkdown(
      [
        '**HR Documents is shared with two groups.**',
        '',
        '## Who has access',
        '| Principal | Role |',
        '| --- | --- |',
        '| HR Members | Edit |',
        '| HR Owners | Full Control |',
        '',
        '- First finding',
        '- Second finding',
        '',
        '1. Review owners',
        '2. Approve the draft',
      ].join('\n'),
    );

    expect(blocks.map((block) => block.kind)).toEqual(['paragraph', 'heading', 'table', 'list', 'list']);
    const table = blocks[2];
    expect(table.kind === 'table' && table.rows.length).toBe(2);
    const bullets = blocks[3];
    expect(bullets.kind === 'list' && !bullets.ordered && bullets.items.length).toBe(2);
    const steps = blocks[4];
    expect(steps.kind === 'list' && steps.ordered).toBeTrue();
  });

  it('keeps only http(s) links as links and turns citations into chips', () => {
    const inlines = parseInline('See [policy](https://contoso.sharepoint.com/doc.docx) 【5:0†source】 and **bold** `code`');
    expect(inlines.map((inline) => inline.kind)).toEqual(['text', 'link', 'text', 'cite', 'text', 'bold', 'text', 'code']);
    const cite = inlines.find((inline) => inline.kind === 'cite');
    expect(cite?.text).toBe('5:0');
    expect(parseInline('[x](javascript:alert(1))').every((inline) => inline.kind !== 'link')).toBeTrue();
  });

  it('never produces markup from angle brackets', () => {
    const [block] = parseMarkdown('<img src=x onerror=alert(1)>');
    expect(block.kind).toBe('paragraph');
  });
});
