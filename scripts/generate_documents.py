#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate 100 richly formatted documents (DOCX, XLSX, PPTX, PDF)
with extensive content including tables, bullets, diagrams, and charts.
Distributes them across SharePoint folders.
"""

import os
import sys
import io
from pathlib import Path
from datetime import datetime

# Fix encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import openpyxl
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.chart import BarChart, PieChart, LineChart, Reference
from pptx import Presentation
from pptx.util import Inches as PptxInches, Pt as PptxPt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor as PptxRGBColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib import colors
from reportlab.pdfgen import canvas
import io

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "generated_documents"

# Create output directory structure
CATEGORIES = ["Quality", "Manufacturing", "Inventory", "Sales", "Supply_Chain", "Yield"]
for category in CATEGORIES:
    category_dir = OUTPUT_DIR / category
    category_dir.mkdir(parents=True, exist_ok=True)

def generate_sample_image(width=400, height=300):
    """Generate a simple PNG image for inclusion in documents."""
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)
    # Draw some shapes to make it look like a diagram
    draw.rectangle([50, 50, 350, 250], outline='blue', width=2)
    draw.ellipse([100, 100, 150, 150], fill='red')
    draw.polygon([(200, 100), (300, 100), (250, 200)], fill='green', outline='black')
    
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

def create_rich_docx(filename, category, doc_number):
    """Create a richly formatted DOCX document with tables, bullets, and images."""
    doc = Document()
    
    # Title
    title = doc.add_heading(f'{category} Analysis Report {doc_number:03d}', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Metadata
    meta_para = doc.add_paragraph()
    meta_para.add_run(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n").italic = True
    meta_para.add_run(f"Category: {category}\n").bold = True
    meta_para.add_run(f"Document ID: SEM-{category[:3].upper()}{doc_number:05d}").font.color.rgb = RGBColor(0, 0, 255)
    
    # Executive Summary
    doc.add_heading('Executive Summary', level=1)
    summary_text = f"""
    This comprehensive report provides an in-depth analysis of {category} operations and performance metrics.
    The document contains detailed findings, statistical analysis, recommendations, and supporting evidence
    compiled from multiple data sources. This report is structured to provide actionable insights for
    decision-makers and operational teams.
    """
    doc.add_paragraph(summary_text)
    
    # Key Findings section with bullets
    doc.add_heading('Key Findings', level=2)
    findings = [
        "Performance improvement of 25% YoY across all metrics",
        "Identification of three critical process bottlenecks requiring intervention",
        "Cost reduction opportunities totaling $2.5M annually",
        "Risk mitigation strategy recommended for Q3-Q4",
        "Compliance status: 98% adherence to operational standards"
    ]
    for finding in findings:
        doc.add_paragraph(finding, style='List Bullet')
    
    # Table 1: Performance Metrics
    doc.add_heading('Performance Metrics Table', level=2)
    table = doc.add_table(rows=6, cols=4)
    table.style = 'Light Grid Accent 1'
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Metric'
    hdr_cells[1].text = 'Q1'
    hdr_cells[2].text = 'Q2'
    hdr_cells[3].text = 'Q3'
    
    metrics = [
        ('Production', '85.2%', '87.5%', '89.1%'),
        ('Quality Score', '92.3%', '94.1%', '95.7%'),
        ('Efficiency', '78.5%', '81.2%', '84.3%'),
        ('Cost Index', '98.2', '96.5%', '94.8%'),
    ]
    
    for i, (metric, q1, q2, q3) in enumerate(metrics, 1):
        row_cells = table.rows[i].cells
        row_cells[0].text = metric
        row_cells[1].text = q1
        row_cells[2].text = q2
        row_cells[3].text = q3
    
    # Add sample image
    doc.add_heading('Analytical Diagrams', level=2)
    img_bytes = generate_sample_image()
    doc.add_picture(img_bytes, width=Inches(5))
    
    # Detailed Analysis Sections (at least 10 pages worth)
    for section_num in range(8):
        doc.add_heading(f'Detailed Analysis - Section {section_num + 1}', level=2)
        
        doc.add_paragraph(
            f"""This section provides comprehensive analysis of {category} metrics for subsection {section_num + 1}.
            Our analysis reveals significant trends and patterns that warrant attention from stakeholders.
            The following data points have been systematically collected and analyzed using industry-standard
            methodologies to ensure accuracy and relevance.
            
            Key observations include improved efficiency metrics, enhanced quality standards, and optimized
            resource allocation across all operational areas. These improvements directly correlate with
            our strategic initiatives implemented over the past fiscal year.
            """
        )
        
        # Add a nested table for detailed metrics
        detail_table = doc.add_table(rows=4, cols=3)
        detail_table.style = 'Light Grid Accent 1'
        hdr = detail_table.rows[0].cells
        hdr[0].text = 'Component'
        hdr[1].text = 'Value'
        hdr[2].text = 'Status'
        
        components = [
            ('Subsystem A', '94.2%', '✓ Optimal'),
            ('Subsystem B', '87.5%', '✓ Good'),
            ('Subsystem C', '79.3%', '⚠ Monitor'),
        ]
        
        for i, (comp, val, status) in enumerate(components, 1):
            row = detail_table.rows[i].cells
            row[0].text = comp
            row[1].text = val
            row[2].text = status
        
        doc.add_paragraph()  # Spacing
    
    # Recommendations
    doc.add_heading('Recommendations', level=1)
    recommendations = [
        "Implement advanced analytics dashboard for real-time monitoring",
        "Schedule quarterly review meetings with stakeholder teams",
        "Invest in automation to reduce manual processes by 30%",
        "Establish KPI tracking system with automated alerts",
        "Conduct staff training programs on new procedures"
    ]
    for i, rec in enumerate(recommendations, 1):
        doc.add_paragraph(f"R{i}: {rec}", style='List Number')
    
    # Appendix
    doc.add_page_break()
    doc.add_heading('Appendix: Data Dictionary', level=1)
    appendix_table = doc.add_table(rows=6, cols=2)
    appendix_table.style = 'Light Grid Accent 1'
    hdr = appendix_table.rows[0].cells
    hdr[0].text = 'Term'
    hdr[1].text = 'Definition'
    
    terms = [
        ('KPI', 'Key Performance Indicator'),
        ('QA', 'Quality Assurance'),
        ('ROI', 'Return on Investment'),
        ('SLA', 'Service Level Agreement'),
        ('YoY', 'Year over Year'),
    ]
    
    for i, (term, defn) in enumerate(terms, 1):
        row = appendix_table.rows[i].cells
        row[0].text = term
        row[1].text = defn
    
    doc.save(filename)

def create_rich_xlsx(filename, category, doc_number):
    """Create a richly formatted XLSX document with charts and data."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    
    # Title
    ws['A1'] = f'{category} Analysis - Document {doc_number:03d}'
    ws['A1'].font = Font(size=16, bold=True, color="FFFFFF")
    ws['A1'].fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    ws.merge_cells('A1:D1')
    
    # Metadata
    ws['A2'] = f"Generated: {datetime.now().strftime('%Y-%m-%d')}"
    ws['A3'] = f"Category: {category}"
    
    # Main Data Table
    ws['A5'] = 'Month'
    ws['B5'] = 'Revenue'
    ws['C5'] = 'Expenses'
    ws['D5'] = 'Profit'
    
    header_fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
    header_font = Font(bold=True)
    
    for col in ['A', 'B', 'C', 'D']:
        ws[f'{col}5'].fill = header_fill
        ws[f'{col}5'].font = header_font
    
    # Data rows
    months = ['January', 'February', 'March', 'April', 'May', 'June', 
              'July', 'August', 'September', 'October', 'November', 'December']
    
    for i, month in enumerate(months, 6):
        ws[f'A{i}'] = month
        ws[f'B{i}'] = (50000 + i * 5000)
        ws[f'C{i}'] = (30000 + i * 2000)
        ws[f'D{i}'] = f'=B{i}-C{i}'
        
        # Alternating row colors
        if i % 2 == 0:
            fill = PatternFill(start_color="F0F0F0", end_color="F0F0F0", fill_type="solid")
            for col in ['A', 'B', 'C', 'D']:
                ws[f'{col}{i}'].fill = fill
    
    # Additional sheets with detailed data
    for sheet_num in range(5):
        sheet = wb.create_sheet(f"Details_{sheet_num + 1}")
        
        # Headers
        headers = ['ID', 'Name', 'Value', 'Status', 'Trend']
        for col_num, header in enumerate(headers, 1):
            cell = sheet.cell(row=1, column=col_num)
            cell.value = header
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        
        # Data rows
        for row_num in range(2, 102):  # 100 rows of data
            sheet.cell(row=row_num, column=1).value = f"ID_{row_num - 1:04d}"
            sheet.cell(row=row_num, column=2).value = f"Item_{row_num - 1}"
            sheet.cell(row=row_num, column=3).value = (1000 + row_num * 10) % 10000
            sheet.cell(row=row_num, column=4).value = ['Active', 'Inactive', 'Pending'][row_num % 3]
            sheet.cell(row=row_num, column=5).value = ['↑', '→', '↓'][row_num % 3]
    
    # Add charts to summary sheet
    chart = BarChart()
    chart.type = "col"
    chart.title = f"{category} Revenue vs Expenses"
    chart.y_axis.title = 'Amount ($)'
    chart.x_axis.title = 'Month'
    
    data = Reference(ws, min_col=2, min_row=5, max_row=17, max_col=3)
    chart.add_data(data, titles_from_data=True)
    ws.add_chart(chart, "F5")
    
    wb.save(filename)

def create_rich_pptx(filename, category, doc_number):
    """Create a richly formatted PPTX presentation."""
    prs = Presentation()
    prs.slide_width = PptxInches(10)
    prs.slide_height = PptxInches(7.5)
    
    # Slide 1: Title
    title_slide_layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(title_slide_layout)
    title = slide.shapes.title
    subtitle = slide.placeholders[1]
    
    title.text = f"{category} Analysis - Document {doc_number:03d}"
    subtitle.text = f"Generated: {datetime.now().strftime('%B %d, %Y')}\nDocument ID: SEM-{category[:3].upper()}{doc_number:05d}"
    
    # Content slides
    for slide_num in range(15):
        blank_slide_layout = prs.slide_layouts[5]  # Blank layout
        slide = prs.slides.add_slide(blank_slide_layout)
        
        # Add title
        title_box = slide.shapes.add_textbox(PptxInches(0.5), PptxInches(0.3), PptxInches(9), PptxInches(1))
        title_frame = title_box.text_frame
        title_frame.text = f"Analysis Section {slide_num + 1}"
        title_frame.paragraphs[0].font.size = PptxPt(44)
        title_frame.paragraphs[0].font.bold = True
        title_frame.paragraphs[0].font.color.rgb = PptxRGBColor(0, 51, 102)
        
        # Add content
        content_box = slide.shapes.add_textbox(PptxInches(0.5), PptxInches(1.2), PptxInches(9), PptxInches(5.5))
        text_frame = content_box.text_frame
        text_frame.word_wrap = True
        
        bullet_points = [
            f"Key insight {slide_num + 1}: Strategic analysis point with detailed information",
            f"Supporting data indicates {75 + slide_num}% improvement in metrics",
            f"Recommended action items for immediate implementation",
            f"Expected ROI: ${100000 + slide_num * 10000} within 6 months",
        ]
        
        for bullet_idx, bullet in enumerate(bullet_points):
            if bullet_idx == 0:
                p = text_frame.paragraphs[0]
            else:
                p = text_frame.add_paragraph()
            p.text = bullet
            p.level = 0
            p.font.size = PptxPt(18)
            p.space_before = PptxPt(6)
            p.space_after = PptxPt(6)
    
    prs.save(filename)

def create_rich_pdf(filename, category, doc_number):
    """Create a richly formatted PDF document."""
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.pagesizes import letter
    
    doc = SimpleDocTemplate(str(filename), pagesize=letter,
                           rightMargin=72, leftMargin=72,
                           topMargin=72, bottomMargin=18)
    
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#003366'),
        spaceAfter=30,
        alignment=1
    )
    story.append(Paragraph(f"{category} Analysis Report {doc_number:03d}", title_style))
    story.append(Spacer(1, 0.3*inch))
    
    # Metadata
    meta_style = ParagraphStyle(
        'Meta',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.grey
    )
    story.append(Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", meta_style))
    story.append(Paragraph(f"<b>Category:</b> {category}", meta_style))
    story.append(Paragraph(f"<b>Document ID:</b> SEM-{category[:3].upper()}{doc_number:05d}", meta_style))
    story.append(Spacer(1, 0.3*inch))
    
    # Executive Summary
    story.append(Paragraph("Executive Summary", styles['Heading1']))
    summary = f"""
    This comprehensive analysis provides detailed insights into {category} performance metrics.
    The report includes statistical analysis, trend evaluation, and strategic recommendations
    based on current operational data and historical benchmarks.
    """
    story.append(Paragraph(summary, styles['BodyText']))
    story.append(Spacer(1, 0.2*inch))
    
    # Add multiple sections to reach 100+ pages
    for section_num in range(50):
        if section_num % 10 == 0 and section_num > 0:
            story.append(PageBreak())
        
        story.append(Paragraph(f"Section {section_num + 1}: Detailed Analysis", styles['Heading2']))
        
        # Content table
        data = [
            ['Metric', 'Value', 'Status', 'Trend'],
            ['Performance', f'{85 + section_num % 10}%', 'Good', '↑'],
            ['Quality', f'{90 + section_num % 8}%', 'Excellent', '↑'],
            ['Cost', f'${50000 - section_num * 100}', 'Controlled', '↓'],
            ['Timeline', f'{100 - section_num % 5}%', 'On-track', '→'],
        ]
        
        table = Table(data, colWidths=[1.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D3D3D3')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 0.2*inch))
        
        # Bullet points
        bullets = [
            f"Analysis point {i + 1}: Key finding from operational review",
            f"Supporting evidence: {75 + i}% correlation with industry standards",
            f"Recommendation: Implement process improvement initiative",
        ]
        
        for bullet in bullets:
            story.append(Paragraph(f"• {bullet}", styles['Normal']))
        
        story.append(Spacer(1, 0.1*inch))
    
    # Build PDF
    doc.build(story)

def main():
    """Main function to generate all documents."""
    print("Starting document generation...")
    
    doc_count = 0
    docs_per_category = 100 // len(CATEGORIES)
    
    for category_idx, category in enumerate(CATEGORIES):
        category_dir = OUTPUT_DIR / category
        start_num = category_idx * docs_per_category + 1
        
        print(f"\nGenerating {docs_per_category} documents for {category}...")
        
        for doc_num in range(docs_per_category):
            actual_doc_num = start_num + doc_num
            base_filename = f"{category}_Document_{actual_doc_num:03d}"
            
            try:
                # DOCX
                try:
                    docx_file = category_dir / f"{base_filename}.docx"
                    create_rich_docx(str(docx_file), category, actual_doc_num)
                    print(f"  + {docx_file.name}")
                    doc_count += 1
                except Exception as e:
                    print(f"  - DOCX error: {e}")
                
                # XLSX
                try:
                    xlsx_file = category_dir / f"{base_filename}.xlsx"
                    create_rich_xlsx(str(xlsx_file), category, actual_doc_num)
                    print(f"  + {xlsx_file.name}")
                    doc_count += 1
                except Exception as e:
                    print(f"  - XLSX error: {e}")
                
                # PPTX (optional, can be slow)
                try:
                    pptx_file = category_dir / f"{base_filename}.pptx"
                    create_rich_pptx(str(pptx_file), category, actual_doc_num)
                    print(f"  + {pptx_file.name}")
                    doc_count += 1
                except Exception as e:
                    print(f"  - PPTX skipped: {e}")
                
                # PDF (optional, can be slow)
                try:
                    pdf_file = category_dir / f"{base_filename}.pdf"
                    create_rich_pdf(str(pdf_file), category, actual_doc_num)
                    print(f"  + {pdf_file.name}")
                    doc_count += 1
                except Exception as e:
                    print(f"  - PDF skipped: {e}")
                
            except Exception as e:
                print(f"  ERROR: {base_filename}: {e}")
    
    print(f"\n✓ Successfully generated {doc_count} documents in {OUTPUT_DIR}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
