import { DocumentPreview, DocumentPreviewBlock, DocumentPreviewSlide } from '../../core/api/models/api.models';

/** Rows that differ from the other document, on one side of a comparison. Units are pages, slides or sheets, numbered from 1. */
export interface DocumentChanges {
  readonly units: ReadonlySet<number>;
  readonly rows: ReadonlySet<string>;
}

export interface DocumentComparison {
  readonly left: DocumentChanges;
  readonly right: DocumentChanges;
}

/** A block index within a unit, or `'title'` for the page, slide or sheet title. */
export type ChangePart = number | 'title';

/** Key of one rendered row in `DocumentChanges.rows`. Blocks with a single row (text, image) use row 0. */
export function changeKey(unit: number, part: ChangePart, row = 0): string {
  return `${unit}:${part}:${row}`;
}

/** Pages (docx, pdf) or slides (pptx), or the one synthetic page shown for a docx without page breaks. */
export function previewPages(preview: DocumentPreview): DocumentPreviewSlide[] {
  if (preview.kind === 'pptx' && preview.slides?.length) return preview.slides;
  if ((preview.kind === 'docx' || preview.kind === 'pdf') && preview.pages?.length) return preview.pages;
  if (preview.kind === 'docx' && (preview.blocks?.length || preview.tables?.length)) {
    const blocks: DocumentPreviewBlock[] = [
      ...(preview.blocks ?? []),
      ...(preview.tables ?? []).map((table) => ({ kind: 'table' as const, table })),
    ];
    return [{ number: 1, title: 'Page 1', blocks }];
  }
  return [];
}

/** Each xlsx sheet is one unit: its grid is block 0 and its images follow as blocks 1..n. */
function comparisonUnits(preview: DocumentPreview): DocumentPreviewSlide[] {
  if (preview.kind !== 'xlsx') return previewPages(preview);
  return (preview.sheets ?? []).map((sheet, index): DocumentPreviewSlide => ({
    number: index + 1,
    title: sheet.name,
    blocks: [
      { kind: 'table', table: sheet.rows },
      ...(sheet.images ?? []).map((image): DocumentPreviewBlock => ({ kind: 'image', image })),
    ],
  }));
}

interface UnitRow {
  part: ChangePart;
  row: number;
  signature: string;
}

const CELL_SEPARATOR = '\u001f';

/** Above this many cells the exact alignment is skipped and identical rows are matched instead. */
const MAX_ALIGNMENT_CELLS = 1_000_000;

function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

/** FNV-1a fingerprint of an image data URL, which keeps row signatures short. */
function fingerprint(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${(hash >>> 0).toString(36)}.${value.length}`;
}

/** Rows in render order, starting with the title. Whitespace is normalized so spacing-only edits are not changes. */
function unitRows(unit: DocumentPreviewSlide): UnitRow[] {
  const rows: UnitRow[] = [{ part: 'title', row: 0, signature: normalizeText(unit.title) }];
  unit.blocks.forEach((block, part) => {
    const text = normalizeText(block.text ?? '');
    if (text) {
      rows.push({ part, row: 0, signature: text });
    }
    (block.lines ?? []).forEach((line, row) => {
      rows.push({ part, row, signature: normalizeText(line) });
    });
    (block.table ?? []).forEach((cells, row) => {
      rows.push({ part, row, signature: cells.map(normalizeText).join(CELL_SEPARATOR) });
    });
    if (block.image) {
      rows.push({ part, row: 0, signature: `image:${fingerprint(block.image)}` });
    }
  });
  return rows;
}

interface Matched {
  left: boolean[];
  right: boolean[];
}

interface Region {
  start: number;
  leftEnd: number;
  rightEnd: number;
}

/** Marks rows that align with a row on the other side. Shared leading and trailing rows match first, then the middle is aligned. */
function matchRows(left: readonly string[], right: readonly string[]): Matched {
  const matched: Matched = { left: left.map(() => false), right: right.map(() => false) };
  let start = 0;
  while (start < left.length && start < right.length && left[start] === right[start]) {
    matched.left[start] = true;
    matched.right[start] = true;
    start++;
  }
  let leftEnd = left.length;
  let rightEnd = right.length;
  while (leftEnd > start && rightEnd > start && left[leftEnd - 1] === right[rightEnd - 1]) {
    leftEnd--;
    rightEnd--;
    matched.left[leftEnd] = true;
    matched.right[rightEnd] = true;
  }
  const region: Region = { start, leftEnd, rightEnd };
  if ((leftEnd - start) * (rightEnd - start) > MAX_ALIGNMENT_CELLS) {
    matchBySignature(left, right, region, matched);
  } else {
    matchByLcs(left, right, region, matched);
  }
  return matched;
}

/** Longest common subsequence of the middle region, so a row is only unmatched when alignment cannot keep it. */
function matchByLcs(left: readonly string[], right: readonly string[], region: Region, matched: Matched): void {
  const n = region.leftEnd - region.start;
  const m = region.rightEnd - region.start;
  const width = m + 1;
  const lengths = new Uint32Array((n + 1) * width);
  for (let a = n - 1; a >= 0; a--) {
    for (let b = m - 1; b >= 0; b--) {
      lengths[a * width + b] = left[region.start + a] === right[region.start + b]
        ? lengths[(a + 1) * width + b + 1] + 1
        : Math.max(lengths[(a + 1) * width + b], lengths[a * width + b + 1]);
    }
  }
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (left[region.start + i] === right[region.start + j]) {
      matched.left[region.start + i] = true;
      matched.right[region.start + j] = true;
      i++;
      j++;
    } else if (lengths[(i + 1) * width + j] >= lengths[i * width + j + 1]) {
      i++;
    } else {
      j++;
    }
  }
}

/** Fallback for regions too large to align: a row matches any unused row on the other side with the same content. */
function matchBySignature(left: readonly string[], right: readonly string[], region: Region, matched: Matched): void {
  const rightRows = new Map<string, number[]>();
  for (let index = region.start; index < region.rightEnd; index++) {
    const indexes = rightRows.get(right[index]) ?? [];
    indexes.push(index);
    rightRows.set(right[index], indexes);
  }
  for (let index = region.start; index < region.leftEnd; index++) {
    const match = rightRows.get(left[index])?.pop();
    if (match !== undefined) {
      matched.left[index] = true;
      matched.right[match] = true;
    }
  }
}

interface MutableChanges {
  units: Set<number>;
  rows: Set<string>;
}

function newChanges(): MutableChanges {
  return { units: new Set<number>(), rows: new Set<string>() };
}

function recordUnmatched(changes: MutableChanges, unit: number, rows: UnitRow[], matched: boolean[]): void {
  rows.forEach((row, index) => {
    if (!matched[index]) {
      changes.units.add(unit);
      changes.rows.add(changeKey(unit, row.part, row.row));
    }
  });
}

/**
 * Compares two previews once, so both panes highlight the same rows. Pages, slides or sheets are paired by position
 * and their rows aligned within each pair, so an inserted row is reported without flagging the rows around it.
 */
export function diffDocumentPreviews(left: DocumentPreview, right: DocumentPreview): DocumentComparison {
  const leftUnits = comparisonUnits(left);
  const rightUnits = comparisonUnits(right);
  const changes = { left: newChanges(), right: newChanges() };
  const count = Math.max(leftUnits.length, rightUnits.length);
  for (let index = 0; index < count; index++) {
    const leftUnit = leftUnits.at(index);
    const rightUnit = rightUnits.at(index);
    const leftRows = leftUnit ? unitRows(leftUnit) : [];
    const rightRows = rightUnit ? unitRows(rightUnit) : [];
    const matched = matchRows(leftRows.map((row) => row.signature), rightRows.map((row) => row.signature));
    if (leftUnit) {
      recordUnmatched(changes.left, leftUnit.number, leftRows, matched.left);
    }
    if (rightUnit) {
      recordUnmatched(changes.right, rightUnit.number, rightRows, matched.right);
    }
  }
  return changes;
}
