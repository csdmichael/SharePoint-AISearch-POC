/** RFC 4180 style CSV: fields with the delimiter, quotes, or line breaks are quoted and quotes are doubled. */
export function toCsv(headers: string[], rows: string[][], delimiter: string, includeBom: boolean): string {
  const escape = (value: string): string => {
    const needsQuotes = value.includes('"') || value.includes('\n') || value.includes('\r') || value.includes(delimiter);
    return needsQuotes ? `"${value.replace(/"/g, '""')}"` : value;
  };
  const lines = [headers, ...rows].map((row) => row.map(escape).join(delimiter));
  return (includeBom ? '\uFEFF' : '') + lines.join('\r\n');
}

/** Saves text as a file through a temporary object URL. */
export function downloadText(doc: Document, fileName: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = doc.createElement('a');
  link.href = url;
  link.download = fileName;
  link.rel = 'noopener';
  doc.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
