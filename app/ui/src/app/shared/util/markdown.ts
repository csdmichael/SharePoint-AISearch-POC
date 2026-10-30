/** Minimal, safe Markdown parser for agent answers. It produces tokens that Angular templates render, never HTML. */

export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'bold'; text: string }
  | { kind: 'italic'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'link'; text: string; href: string }
  | { kind: 'cite'; text: string };

export type MarkdownBlock =
  | { kind: 'heading'; level: 1 | 2 | 3 | 4; inlines: Inline[] }
  | { kind: 'paragraph'; inlines: Inline[] }
  | { kind: 'list'; ordered: boolean; items: Inline[][] }
  | { kind: 'table'; headers: Inline[][]; rows: Inline[][][] }
  | { kind: 'quote'; inlines: Inline[] }
  | { kind: 'code'; text: string }
  | { kind: 'rule' };

const INLINE_PATTERN = /(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))|(\*\*([^*]+)\*\*)|(`([^`]+)`)|(\*([^*\s][^*]*)\*)|(【[^】]*】)/g;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;

export function parseInline(text: string): Inline[] {
  const result: Inline[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE_PATTERN)) {
    const index = match.index ?? 0;
    if (index > last) {
      result.push({ kind: 'text', text: text.slice(last, index) });
    }
    if (match[1]) {
      result.push({ kind: 'link', text: match[2], href: match[3] });
    } else if (match[4]) {
      result.push({ kind: 'bold', text: match[5] });
    } else if (match[6]) {
      result.push({ kind: 'code', text: match[7] });
    } else if (match[10]) {
      result.push({ kind: 'cite', text: match[10].replace(/[【】]/g, '').split('†')[0] });
    } else {
      result.push({ kind: 'italic', text: match[9] });
    }
    last = index + match[0].length;
  }
  if (last < text.length) {
    result.push({ kind: 'text', text: text.slice(last) });
  }
  return result;
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return trimmed.split('|').map((cell) => cell.trim());
}

function isTableStart(lines: string[], index: number): boolean {
  return lines[index].includes('|') && index + 1 < lines.length && TABLE_SEPARATOR.test(lines[index + 1]) && lines[index + 1].includes('-');
}

export function parseMarkdown(source: string): MarkdownBlock[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let i = 0;

  const flushParagraph = (): void => {
    if (paragraph.length > 0) {
      blocks.push({ kind: 'paragraph', inlines: parseInline(paragraph.join(' ')) });
      paragraph = [];
    }
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed === '') {
      flushParagraph();
      i++;
      continue;
    }
    if (trimmed.startsWith('```')) {
      flushParagraph();
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        code.push(lines[i]);
        i++;
      }
      i++;
      blocks.push({ kind: 'code', text: code.join('\n') });
      continue;
    }
    const heading = /^(#{1,4})\s+(.*?)\s*#*$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      blocks.push({ kind: 'heading', level: heading[1].length as 1 | 2 | 3 | 4, inlines: parseInline(heading[2]) });
      i++;
      continue;
    }
    if (/^([-*_])\1{2,}$/.test(trimmed.replace(/\s/g, ''))) {
      flushParagraph();
      blocks.push({ kind: 'rule' });
      i++;
      continue;
    }
    if (isTableStart(lines, i)) {
      flushParagraph();
      const headers = splitRow(line).map(parseInline);
      i += 2;
      const rows: Inline[][][] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(splitRow(lines[i]).map(parseInline));
        i++;
      }
      blocks.push({ kind: 'table', headers, rows });
      continue;
    }
    if (trimmed.startsWith('>')) {
      flushParagraph();
      const quote: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        quote.push(lines[i].trim().replace(/^>\s?/, ''));
        i++;
      }
      blocks.push({ kind: 'quote', inlines: parseInline(quote.join(' ')) });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = !bullet;
      const pattern = ordered ? NUMBERED : BULLET;
      const items: Inline[][] = [];
      while (i < lines.length) {
        const item = pattern.exec(lines[i]);
        if (item) {
          items.push(parseInline(item[1]));
          i++;
        } else if (/^\s{2,}\S/.test(lines[i]) && items.length > 0 && !BULLET.test(lines[i]) && !NUMBERED.test(lines[i])) {
          items[items.length - 1].push(...parseInline(' ' + lines[i].trim()));
          i++;
        } else {
          break;
        }
      }
      blocks.push({ kind: 'list', ordered, items });
      continue;
    }
    paragraph.push(trimmed);
    i++;
  }
  flushParagraph();
  return blocks;
}
