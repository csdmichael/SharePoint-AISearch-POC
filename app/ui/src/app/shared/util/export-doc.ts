/**
 * Comprehensive document export utility for the Governance UI.
 * Supports exporting structured agent output and governance data to:
 * - Microsoft Excel (.xls / CSV)
 * - Microsoft Word (.doc)
 * - Microsoft PowerPoint (.ppt / presentation outline)
 */

import { AgentCitation, AgentEvidence, AgentReply } from '../../core/api/models/api.models';
import { downloadText } from './csv';

/** Exports tabular data to an Excel-compatible XML spreadsheet (.xls) */
export function exportToExcel(
  doc: Document,
  fileName: string,
  title: string,
  headers: string[],
  rows: (string | number | boolean | null)[][],
  extraFacts?: Record<string, unknown>,
): void {
  const safeTitle = escapeXml(title);
  let xml = `<?xml version="1.0" encoding="utf-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:html="http://www.w3.org/TR/REC-html40">
 <Styles>
  <Style ss:ID="Default" ss:Name="Normal">
   <Alignment ss:Vertical="Center"/>
   <Font ss:FontName="Segoe UI" ss:Size="10" ss:Color="#1F2937"/>
  </Style>
  <Style ss:ID="Header">
   <Alignment ss:Horizontal="Center" ss:Vertical="Center"/>
   <Borders>
    <Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="2" ss:Color="#0078D4"/>
   </Borders>
   <Font ss:FontName="Segoe UI" ss:Size="11" ss:Bold="1" ss:Color="#FFFFFF"/>
   <Interior ss:Color="#0078D4" ss:Pattern="Solid"/>
  </Style>
  <Style ss:ID="Title">
   <Font ss:FontName="Segoe UI" ss:Size="14" ss:Bold="1" ss:Color="#0078D4"/>
  </Style>
  <Style ss:ID="Muted">
   <Font ss:FontName="Segoe UI" ss:Size="9" ss:Italic="1" ss:Color="#6B7280"/>
  </Style>
 </Styles>
 <Worksheet ss:Name="Governance Data">
  <Table>
   <Row>
    <Cell ss:StyleID="Title"><Data ss:Type="String">${safeTitle}</Data></Cell>
   </Row>
   <Row>
    <Cell ss:StyleID="Muted"><Data ss:Type="String">Exported on ${new Date().toLocaleString()}</Data></Cell>
   </Row>
   <Row></Row>`;

  if (extraFacts && Object.keys(extraFacts).length > 0) {
    xml += `
   <Row><Cell ss:StyleID="Title"><Data ss:Type="String">Summary Metrics</Data></Cell></Row>`;
    for (const [key, val] of Object.entries(extraFacts)) {
      xml += `
   <Row>
    <Cell><Data ss:Type="String">${escapeXml(key)}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(String(val))}</Data></Cell>
   </Row>`;
    }
    xml += `<Row></Row>`;
  }

  // Headers
  if (headers.length > 0) {
    xml += `
   <Row>`;
    for (const header of headers) {
      xml += `<Cell ss:StyleID="Header"><Data ss:Type="String">${escapeXml(header)}</Data></Cell>`;
    }
    xml += `</Row>`;
  }

  // Rows
  for (const row of rows) {
    xml += `
   <Row>`;
    for (const cell of row) {
      if (typeof cell === 'number') {
        xml += `<Cell><Data ss:Type="Number">${cell}</Data></Cell>`;
      } else {
        xml += `<Cell><Data ss:Type="String">${escapeXml(cell === null ? '' : String(cell))}</Data></Cell>`;
      }
    }
    xml += `</Row>`;
  }

  xml += `
  </Table>
 </Worksheet>
</Workbook>`;

  downloadText(doc, `${fileName}.xls`, xml, 'application/vnd.ms-excel;charset=utf-8');
}

/** Exports agent response and evidence to a styled Microsoft Word document (.doc) */
export function exportToWord(
  doc: Document,
  fileName: string,
  title: string,
  answer: string,
  citations: AgentCitation[],
  evidence?: AgentEvidence | null,
): void {
  const safeTitle = escapeXml(title);
  const formattedAnswer = answer
    .split('\n')
    .map((line) => {
      const trimmed = line.trim();
      if (!trimmed) return '<br/>';
      if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        return `<li>${escapeXml(trimmed.substring(2))}</li>`;
      }
      return `<p style="margin: 6px 0; font-size: 11pt; line-height: 1.5;">${escapeXml(trimmed)}</p>`;
    })
    .join('');

  let tableHtml = '';
  if (evidence && evidence.rows.length > 0) {
    tableHtml = `
      <h3 style="color: #0078D4; margin-top: 20px; font-size: 12pt; border-bottom: 1px solid #E5E7EB; padding-bottom: 4px;">Supporting Evidence</h3>
      <table style="width: 100%; border-collapse: collapse; margin-top: 10px; font-family: Segoe UI, sans-serif; font-size: 10pt;">
        <thead>
          <tr style="background-color: #0078D4; color: white;">
            ${evidence.columns.map((c) => `<th style="padding: 8px; border: 1px solid #D1D5DB; text-align: left;">${escapeXml(c)}</th>`).join('')}
          </tr>
        </thead>
        <tbody>
          ${evidence.rows
            .map(
              (r, idx) => `
            <tr style="background-color: ${idx % 2 === 0 ? '#FFFFFF' : '#F9FAFB'};">
              ${r.map((c) => `<td style="padding: 6px 8px; border: 1px solid #E5E7EB;">${escapeXml(c === null ? '' : String(c))}</td>`).join('')}
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>`;
  }

  let citationsHtml = '';
  if (citations && citations.length > 0) {
    citationsHtml = `
      <h3 style="color: #0078D4; margin-top: 20px; font-size: 12pt; border-bottom: 1px solid #E5E7EB; padding-bottom: 4px;">Document Citations</h3>
      <ul style="font-size: 10pt; color: #374151; margin-top: 8px;">
        ${citations.map((c) => `<li style="margin-bottom: 4px;"><strong>${escapeXml(c.title)}</strong>: <a href="${escapeXml(c.url)}" style="color: #0078D4;">${escapeXml(c.url)}</a></li>`).join('')}
      </ul>`;
  }

  const wordHtml = `<html xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:w="urn:schemas-microsoft-com:office:word"
 xmlns="http://www.w3.org/TR/REC-html40">
<head>
  <meta charset="utf-8">
  <title>${safeTitle}</title>
  <style>
    body { font-family: 'Segoe UI', Arial, sans-serif; color: #1F2937; margin: 24px; }
    h1 { color: #0078D4; font-size: 18pt; margin-bottom: 4px; border-bottom: 2px solid #0078D4; padding-bottom: 8px; }
    .meta { color: #6B7280; font-size: 9pt; margin-bottom: 18px; }
    ul { margin: 8px 0; padding-left: 20px; }
    li { margin-bottom: 4px; }
  </style>
</head>
<body>
  <h1>${safeTitle}</h1>
  <div class="meta">SharePoint Knowledge Governance Assistant &bull; Generated on ${new Date().toLocaleString()}</div>
  <div class="content">${formattedAnswer}</div>
  ${tableHtml}
  ${citationsHtml}
</body>
</html>`;

  downloadText(doc, `${fileName}.doc`, wordHtml, 'application/msword;charset=utf-8');
}

/** Exports agent response and metrics to a PowerPoint slide presentation (.ppt) */
export function exportToPpt(
  doc: Document,
  fileName: string,
  title: string,
  answer: string,
  citations: AgentCitation[],
  metrics?: Record<string, unknown>,
): void {
  const safeTitle = escapeXml(title);
  const bulletLines = answer
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0 && !l.startsWith('#'))
    .slice(0, 8);

  let metricsHtml = '';
  if (metrics && Object.keys(metrics).length > 0) {
    metricsHtml = `
      <div style="background-color: #F3F4F6; padding: 12px; border-radius: 6px; margin-top: 15px;">
        <h4 style="margin: 0 0 8px 0; color: #0078D4; font-size: 11pt;">Key Metrics</h4>
        <div style="display: flex; gap: 20px;">
          ${Object.entries(metrics)
            .map(
              ([k, v]) => `
            <div><strong>${escapeXml(k)}:</strong> ${escapeXml(String(v))}</div>`,
            )
            .join('')}
        </div>
      </div>`;
  }

  const pptHtml = `<html xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:p="urn:schemas-microsoft-com:office:powerpoint"
 xmlns="http://www.w3.org/TR/REC-html40">
<head>
  <meta charset="utf-8">
  <title>${safeTitle}</title>
  <style>
    body { font-family: 'Segoe UI', Arial, sans-serif; background-color: #F9FAFB; padding: 20px; }
    .slide {
      background: white;
      border: 1px solid #D1D5DB;
      border-radius: 8px;
      padding: 30px;
      margin-bottom: 24px;
      box-shadow: 0 4px 6px rgba(0,0,0,0.05);
      min-height: 400px;
      page-break-after: always;
    }
    .slide-header { border-bottom: 3px solid #0078D4; padding-bottom: 12px; margin-bottom: 20px; }
    .slide-title { font-size: 20pt; font-weight: bold; color: #0078D4; margin: 0; }
    .slide-subtitle { font-size: 10pt; color: #6B7280; margin-top: 4px; }
    .bullet-list { font-size: 14pt; line-height: 1.6; color: #1F2937; }
    .citation-list { font-size: 10pt; color: #4B5563; margin-top: 20px; border-top: 1px solid #E5E7EB; padding-top: 10px; }
  </style>
</head>
<body>
  <!-- Slide 1: Executive Summary -->
  <div class="slide">
    <div class="slide-header">
      <h2 class="slide-title">${safeTitle}</h2>
      <div class="slide-subtitle">SharePoint Knowledge Governance &bull; ${new Date().toLocaleDateString()}</div>
    </div>
    <ul class="bullet-list">
      ${bulletLines.map((line) => `<li>${escapeXml(line.replace(/^[-*]\s*/, ''))}</li>`).join('')}
    </ul>
    ${metricsHtml}
    ${
      citations.length > 0
        ? `<div class="citation-list"><strong>Sources:</strong> ${citations.map((c) => escapeXml(c.title)).join(', ')}</div>`
        : ''
    }
  </div>
</body>
</html>`;

  downloadText(doc, `${fileName}.ppt`, pptHtml, 'application/vnd.ms-powerpoint;charset=utf-8');
}

function escapeXml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}
