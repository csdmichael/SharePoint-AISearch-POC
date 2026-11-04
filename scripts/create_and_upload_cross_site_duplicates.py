"""Generate and upload cross-site duplicate documents with randomized page-level differences.

This script implements:
1. Four SharePoint sites:
   - HR Knowledge Hub (hr)
   - Manufacturing Knowledge Hub (manufacturing)
   - Sales & Marketing Knowledge Hub (sales)
   - Semiconductor Knowledge Hub (semiconductor)
2. Per site in data/sites/<siteId>:
   - Base document
   - Exact copy (100% identical, same page count)
   - Edited copy (same page count, wording edits on 2 randomly chosen pages)
   - Extended copy (+2 appended pages, wording edits on 3 randomly chosen pages)
   Each edit sits at a seeded-random position on its page (see duplicate_variations.py).
3. Uploads to all 4 SharePoint sites via Microsoft Graph API.
4. Computes exact percentage similarity (overall & page-by-page) and highlights differences.
"""

from __future__ import annotations

import copy
import difflib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

try:
    from .duplicate_variations import EDITED_COPY_PAGES, EXTENDED_COPY_EDITED_PAGES, write_variant
except ImportError:
    from duplicate_variations import EDITED_COPY_PAGES, EXTENDED_COPY_EDITED_PAGES, write_variant


def get_graph_token(tenant_id: str = "12a4b86b-e64c-43f9-af05-d9130a72dfd2") -> str:
    cmd = f"az.cmd account get-access-token --tenant {tenant_id} --resource https://graph.microsoft.com --query accessToken -o tsv"
    output = subprocess.check_output(cmd, shell=True, text=True).strip()
    return output


def extract_pages_from_docx(doc_path: Path | str) -> list[dict[str, Any]]:
    """Extract structured content per page using explicit page breaks in docx."""
    doc = Document(str(doc_path))
    pages: list[dict[str, Any]] = []
    current_paragraphs: list[str] = []

    page_num = 1
    for p in doc.paragraphs:
        has_break = False
        for r in p.runs:
            xml = r._r.xml
            if ("w:br" in xml and 'type="page"' in xml) or ("w:br" in xml and "page" in xml):
                has_break = True
        
        text = p.text.strip()
        if text:
            current_paragraphs.append(text)
        
        if has_break:
            pages.append({
                "page_number": page_num,
                "text": "\n".join(current_paragraphs),
                "paragraphs": list(current_paragraphs),
            })
            page_num += 1
            current_paragraphs = []

    if current_paragraphs:
        pages.append({
            "page_number": page_num,
            "text": "\n".join(current_paragraphs),
            "paragraphs": list(current_paragraphs),
        })

    return pages


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate SequenceMatcher similarity percentage between two texts."""
    if text1 == text2:
        return 100.0
    matcher = difflib.SequenceMatcher(None, text1, text2)
    return round(matcher.ratio() * 100.0, 2)

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor


def get_graph_token(tenant_id: str = "12a4b86b-e64c-43f9-af05-d9130a72dfd2") -> str:
    cmd = f"az.cmd account get-access-token --tenant {tenant_id} --resource https://graph.microsoft.com --query accessToken -o tsv"
    output = subprocess.check_output(cmd, shell=True, text=True).strip()
    return output


def extract_pages_from_docx(doc_path: Path | str) -> list[dict[str, Any]]:
    """Extract structured content per page using explicit page breaks in docx."""
    doc = Document(str(doc_path))
    pages: list[dict[str, Any]] = []
    current_paragraphs: list[str] = []

    page_num = 1
    for p in doc.paragraphs:
        has_break = False
        for r in p.runs:
            xml = r._r.xml
            if ("w:br" in xml and 'type="page"' in xml) or ("w:br" in xml and "page" in xml):
                has_break = True
        
        text = p.text.strip()
        if text:
            current_paragraphs.append(text)
        
        if has_break:
            pages.append({
                "page_number": page_num,
                "text": "\n".join(current_paragraphs),
                "paragraphs": list(current_paragraphs),
            })
            page_num += 1
            current_paragraphs = []

    if current_paragraphs:
        pages.append({
            "page_number": page_num,
            "text": "\n".join(current_paragraphs),
            "paragraphs": list(current_paragraphs),
        })

    return pages


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate SequenceMatcher similarity percentage between two texts."""
    if text1 == text2:
        return 100.0
    matcher = difflib.SequenceMatcher(None, text1, text2)
    return round(matcher.ratio() * 100.0, 2)


def style_table(table):
    table.style = "Light Grid Accent 1"
    for cell in table.rows[0].cells:
        if cell.paragraphs and cell.paragraphs[0].runs:
            cell.paragraphs[0].runs[0].bold = True


# ---------------------------------------------------------------------------
# Document generators
# ---------------------------------------------------------------------------

def generate_manufacturing_docs():
    base_path = Path("data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure.docx")
    copy_path = Path("data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure (copy).docx")
    edited_path = Path("data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure (edited copy).docx")
    extended_path = Path("data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure (extended copy).docx")

    # Ensure exact copy is 100% identical
    shutil.copy2(base_path, copy_path)

    write_variant(base_path, edited_path, pages=EDITED_COPY_PAGES, kind="edited")
    write_variant(base_path, extended_path, pages=EXTENDED_COPY_EDITED_PAGES, kind="extended")

    # Reopen the extended copy so the appended pages follow its edited base pages
    doc_ext = Document(str(extended_path))

    # Page 6: Appendix A
    doc_ext.add_page_break()
    h6 = doc_ext.add_heading("Section 6: Appendix A - Advanced Material Optical Characterization & Spectroscopy Protocol", level=1)
    doc_ext.add_paragraph(
        "Governs non-destructive optical spectroscopy, surface roughness interferometry, and tensile hardness verification "
        "applied to critical alloy incoming raw materials prior to machining."
    )
    doc_ext.add_paragraph(
        "Optical emission spectrometry (OES) must confirm elemental composition against ASTM specifications with zero tolerance for tramp elements.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Surface finish Ra roughness measurements must not exceed 0.8 micrometers across all datum mating surfaces.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Micro-indentation Rockwell hardness testing requires minimum 5 indentations per sample coupon with standard deviation under 1.2 HRC.",
        style="List Bullet"
    )
    t6 = doc_ext.add_table(rows=4, cols=4)
    style_table(t6)
    t6_data = [
        ("Inspection Attribute", "Test Standard", "Specification Limit", "Gage / Tool"),
        ("Tensile Yield Strength", "ASTM E8 / E8M", ">= 485 MPa", "Instron 5985 Universal Tester"),
        ("Rockwell Hardness", "ASTM E18", "32 - 36 HRC", "Wilson VH1150 Macro Vickers"),
        ("Surface Roughness Ra", "ISO 4287", "<= 0.80 um", "Zygo Nexview Optical Profiler"),
    ]
    for r_idx, row in enumerate(t6_data):
        for c_idx, val in enumerate(row):
            t6.rows[r_idx].cells[c_idx].text = val
    doc_ext.add_paragraph("Page 6 of 7 | Manufacturing Knowledge Hub | Quality Assurance | SharePoint Online")

    # Page 7: Appendix B
    doc_ext.add_page_break()
    h7 = doc_ext.add_heading("Section 7: Appendix B - Traceability & Chain-of-Custody Digital Verification Matrix", level=1)
    doc_ext.add_paragraph(
        "Defines end-to-end serialized 2D DataMatrix barcode scanning, supplier heat-lot genealogy tracking, and automated "
        "Certificate of Analysis (CoA) validation into the Manufacturing Execution System (MES)."
    )
    doc_ext.add_paragraph(
        "Each raw material pallet must carry an RFID tag paired with supplier cryptographic mill certificate before receiving dock acceptance.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Batch lot numbers must maintain unbroken lineage linking supplier heat code to finished subassembly serial numbers.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Any broken chain of custody or mismatched serial range triggers an automatic system quarantine lock in SAP ERP.",
        style="List Bullet"
    )
    t7 = doc_ext.add_table(rows=4, cols=4)
    style_table(t7)
    t7_data = [
        ("Verification Gate", "Traceability Identifier", "System of Record", "Sign-off Authority"),
        ("Receiving Dock Intake", "Supplier Heat / Melt Number", "SAP S/4HANA Receiving", "Receiving Inspector"),
        ("Metrology Lab Clearance", "Internal Sample Coupon ID", "LIMS Lab Database", "Quality Metrologist"),
        ("Line 3 Staging Release", "MES Lot Traveler Barcode", "Siemens Opcenter MES", "Shift Quality Lead"),
    ]
    for r_idx, row in enumerate(t7_data):
        for c_idx, val in enumerate(row):
            t7.rows[r_idx].cells[c_idx].text = val
    doc_ext.add_paragraph("Page 7 of 7 | Manufacturing Knowledge Hub | Quality Assurance | SharePoint Online")

    doc_ext.save(extended_path)
    print("[Manufacturing] Generated edited copy (5 pages) and extended copy (7 pages).")


def generate_sales_docs():
    base_path = Path("data/sites/sales/Sales Playbooks/discovery-call-guide.docx")
    copy_path = Path("data/sites/sales/Sales Playbooks/discovery-call-guide (copy).docx")
    edited_path = Path("data/sites/sales/Sales Playbooks/discovery-call-guide (edited copy).docx")
    extended_path = Path("data/sites/sales/Sales Playbooks/discovery-call-guide (extended copy).docx")

    # Ensure exact copy is 100% identical
    shutil.copy2(base_path, copy_path)

    write_variant(base_path, edited_path, pages=EDITED_COPY_PAGES, kind="edited")
    write_variant(base_path, extended_path, pages=EXTENDED_COPY_EDITED_PAGES, kind="extended")

    # Reopen the extended copy so the appended pages follow its edited base pages
    doc_ext = Document(str(extended_path))

    # Page 7: Appendix A
    doc_ext.add_page_break()
    doc_ext.add_heading("Section 7: Appendix A - Executive Sponsor Alignment & Consensus Playbook", level=1)
    doc_ext.add_paragraph(
        "Provides proven engagement frameworks, value realization formulas, and strategic discovery questions tailored "
        "specifically for C-suite decision makers (CIO, CISO, CFO, VP Engineering)."
    )
    doc_ext.add_paragraph(
        "CIO Engagement: Focus on legacy modernization risks, architectural agility, and cross-team developer productivity gains.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "CISO Engagement: Emphasize least-privilege access, FedRAMP/SOC2 certifications, and automated compliance policy guardrails.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "CFO Engagement: Present three-year total cost of ownership (TCO) models comparing current on-premises run rates with cloud migration.",
        style="List Bullet"
    )
    t7 = doc_ext.add_table(rows=4, cols=4)
    style_table(t7)
    t7_data = [
        ("Executive Role", "Primary Value Driver", "Discovery Question Focus", "Success Metric Target"),
        ("Chief Information Officer", "Platform Consolidation", "What technical debt is slowing deployment velocity?", "35% faster time-to-market"),
        ("Chief Information Security Officer", "Data Governance & Zero Trust", "How do you audit cross-cloud AI data exposure?", "100% audit policy compliance"),
        ("Chief Financial Officer", "OpEx Optimization", "What is the annual cost of downtime across core apps?", "< 14 months payback period"),
    ]
    for r_idx, row in enumerate(t7_data):
        for c_idx, val in enumerate(row):
            t7.rows[r_idx].cells[c_idx].text = val
    doc_ext.add_paragraph("Page 7 of 8 | Sales & Marketing Knowledge Hub | Sales Playbooks | SharePoint Online")

    # Page 8: Appendix B
    doc_ext.add_page_break()
    doc_ext.add_heading("Section 8: Appendix B - Enterprise Security, Governance & Regulatory Compliance FAQs", level=1)
    doc_ext.add_paragraph(
        "Pre-approved responses to rigorous customer info-sec questionnaires regarding data residency, tenant isolation, "
        "encryption at rest and in transit, and AI model telemetry privacy."
    )
    doc_ext.add_paragraph(
        "Data Residency: Customer tenant data never leaves the specified Azure geographic region; all processing is isolated.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Zero Model Training: Customer prompt inputs and retrieved embeddings are never used to train public or shared AI models.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Encryption: AES-256 for all at-rest storage; TLS 1.3 enforced for all API traffic and browser sessions.",
        style="List Bullet"
    )
    t8 = doc_ext.add_table(rows=4, cols=4)
    style_table(t8)
    t8_data = [
        ("Security Domain", "Customer Concern", "Architecture Solution", "Compliance Artifact"),
        ("Tenant Isolation", "Cross-tenant data leakage", "Dedicated Azure subscription & VNet pairing", "SOC 2 Type II Report"),
        ("Model Privacy", "Public AI training risks", "Foundry private endpoints & zero-retention logging", "Microsoft AI Trust Addendum"),
        ("Data Sovereignty", "EU data transfer restrictions", "Local West Europe Azure paired region hosting", "ISO 27001 / GDPR DPA"),
    ]
    for r_idx, row in enumerate(t8_data):
        for c_idx, val in enumerate(row):
            t8.rows[r_idx].cells[c_idx].text = val
    doc_ext.add_paragraph("Page 8 of 8 | Sales & Marketing Knowledge Hub | Sales Playbooks | SharePoint Online")

    doc_ext.save(extended_path)
    print("[Sales] Generated edited copy (6 pages) and extended copy (8 pages).")


def generate_hr_docs():
    base_path = Path("data/sites/hr/HR Policies/employee-handbook-code-of-conduct.docx")
    copy_path = Path("data/sites/hr/HR Policies/employee-handbook-code-of-conduct (copy).docx")
    edited_path = Path("data/sites/hr/HR Policies/employee-handbook-code-of-conduct (edited copy).docx")
    extended_path = Path("data/sites/hr/HR Policies/employee-handbook-code-of-conduct (extended copy).docx")

    # Ensure exact copy is 100% identical
    shutil.copy2(base_path, copy_path)

    write_variant(base_path, edited_path, pages=EDITED_COPY_PAGES, kind="edited")
    write_variant(base_path, extended_path, pages=EXTENDED_COPY_EDITED_PAGES, kind="extended")

    # Reopen the extended copy so the appended pages follow its edited base pages
    doc_ext = Document(str(extended_path))

    # Page 12: Addendum A
    doc_ext.add_page_break()
    doc_ext.add_heading("Section 12: Addendum A - Artificial Intelligence & Automated Decision Ethics Policy", level=1)
    doc_ext.add_paragraph(
        "Establishes institutional governance, ethical boundaries, transparency obligations, and human-in-the-loop oversight "
        "standards for workforce AI tools and automated screening systems."
    )
    doc_ext.add_paragraph(
        "Human Oversight: Automated algorithms may inform talent decisions but final hiring, promotion, and termination decisions require human sign-off.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Algorithmic Bias Auditing: Annual third-party demographic parity audits required for all resume screening and interview evaluation tooling.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Employee Transparency: Workforce members have the explicit right to know when an AI system participates in performance evaluations.",
        style="List Bullet"
    )
    t12 = doc_ext.add_table(rows=4, cols=4)
    style_table(t12)
    t12_data = [
        ("AI Use Case", "Risk Tier", "Required Governance Gate", "Monitoring Frequency"),
        ("Resume Parsing & Ranking", "Tier 2 - Medium", "HR Tech Review & EEOC Bias Check", "Quarterly Sampling"),
        ("Performance Calibration AI", "Tier 1 - High", "VP HR & Legal Counsel Approval", "Every Review Cycle"),
        ("Internal Learning Recommendations", "Tier 3 - Low", "Department Lead Notification", "Annual Review"),
    ]
    for r_idx, row in enumerate(t12_data):
        for c_idx, val in enumerate(row):
            t12.rows[r_idx].cells[c_idx].text = val
    doc_ext.add_paragraph("Page 12 of 13 | HR Knowledge Hub | HR Policies | SharePoint Online")

    # Page 13: Addendum B
    doc_ext.add_page_break()
    doc_ext.add_heading("Section 13: Addendum B - Global Mobility & Cross-Border Remote Work Regulatory Framework", level=1)
    doc_ext.add_paragraph(
        "Comprehensive rules governing international remote work, corporate tax nexus avoidance, temporary foreign work authorization, "
        "and statutory benefits coordination across jurisdictions."
    )
    doc_ext.add_paragraph(
        "Maximum Duration: Remote work from an unauthorized non-primary jurisdiction is capped at 30 cumulative days per calendar year.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Tax Nexus Review: Working from foreign countries with permanent establishment risk requires prior Global Tax clearance.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Export Compliance: Handling ITAR, EAR, or sensitive semiconductor IP while outside approved jurisdictions is strictly prohibited.",
        style="List Bullet"
    )
    t13 = doc_ext.add_table(rows=4, cols=4)
    style_table(t13)
    t13_data = [
        ("Mobility Tier", "Permitted Duration", "Tax & Legal Assessment", "Approval Authority"),
        ("Domestic State-to-State", "Up to 60 days / year", "Payroll State Tax Registration", "Direct Manager"),
        ("International Temporary", "Up to 30 days / year", "Permanent Establishment & Visa Check", "VP HR & Corporate Tax"),
        ("Permanent Cross-Border Transfer", "Indefinite", "Full Legal Entity & Local Contract Setup", "Global Mobility Committee"),
    ]
    for r_idx, row in enumerate(t13_data):
        for c_idx, val in enumerate(row):
            t13.rows[r_idx].cells[c_idx].text = val
    doc_ext.add_paragraph("Page 13 of 13 | HR Knowledge Hub | HR Policies | SharePoint Online")

    doc_ext.save(extended_path)
    print("[HR] Generated edited copy (11 pages) and extended copy (13 pages).")


def generate_semiconductor_docs():
    source_corpus = Path("corpus/Quality/defect-analysis-planning-workbook.docx")
    semi_dir = Path("data/sites/semiconductor/Quality")
    semi_dir.mkdir(parents=True, exist_ok=True)

    base_path = semi_dir / "defect-analysis-planning-workbook.docx"
    copy_path = semi_dir / "defect-analysis-planning-workbook (copy).docx"
    edited_path = semi_dir / "defect-analysis-planning-workbook (edited copy).docx"
    extended_path = semi_dir / "defect-analysis-planning-workbook (extended copy).docx"

    # Base and Exact Copy
    shutil.copy2(source_corpus, base_path)
    shutil.copy2(source_corpus, copy_path)

    write_variant(base_path, edited_path, pages=EDITED_COPY_PAGES, kind="edited")
    write_variant(base_path, extended_path, pages=EXTENDED_COPY_EDITED_PAGES, kind="extended")

    # Reopen the extended copy so the appended pages follow its edited base pages
    doc_ext = Document(str(extended_path))

    # Page 6: Addendum 1
    doc_ext.add_page_break()
    doc_ext.add_heading("Page 6: Addendum 1 - In-Line Optical & SEM Defect Review Methodology", level=1)
    doc_ext.add_paragraph(
        "Standard operating procedure for high-throughput Brightfield/Darkfield optical wafer inspection, automated Scanning Electron "
        "Microscopy (SEM) defect review, and Energy-Dispersive X-ray (EDX) elemental identification."
    )
    doc_ext.add_paragraph(
        "Optical Inspection Sensitivity: High-aspect-ratio darkfield inspection detects killer particles down to 18nm threshold.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Automated SEM Re-detection: Top 150 clustered defect coordinates automatically dispatched to in-line SEM for high-resolution imaging.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "EDX Chemical Fingerprint: Material elemental spectra classified into Copper, Tungsten, Polysilicon, or Organic slurry residues.",
        style="List Bullet"
    )
    t6 = doc_ext.add_table(rows=4, cols=4)
    style_table(t6)
    t6_data = [
        ("Defect Classification", "Inspection Tool", "Root Cause Mechanism", "Containment Action"),
        ("Bridging Micro-shorts", "SEM Review Station 2", "EUV Photoresist scumming / under-exposure", "Adjust litho exposure energy +1.5%"),
        ("CMP Scratch Particle", "Darkfield Optical Scanner", "Slurry agglomeration during polishing", "Flush filter cartridges & replace pad"),
        ("Tungsten Plug Void", "Voltage-Contrast SEM", "Chemical vapor deposition gas starvation", "Chamber clean & gas mass-flow calibration"),
    ]
    for r_idx, row in enumerate(t6_data):
        for c_idx, val in enumerate(row):
            t6.rows[r_idx].cells[c_idx].text = val
    doc_ext.add_paragraph("Page 6 of 7 | Semiconductor Knowledge Hub | Quality | SharePoint Online")

    # Page 7: Addendum 2
    doc_ext.add_page_break()
    doc_ext.add_heading("Page 7: Addendum 2 - Advanced Packaging Die-to-Wafer Interconnect Yield Analysis", level=1)
    doc_ext.add_paragraph(
        "Focuses on 2.5D/3D heterogeneous chiplet integration yield loss mechanisms, micro-bump solder bridging, silicon interposer "
        "through-silicon via (TSV) connectivity, and High-Bandwidth Memory (HBM3e) stack yield optimization."
    )
    doc_ext.add_paragraph(
        "Micro-bump Joint Coplanarity: Non-contact optical metrology ensures bump height variance stays within +/- 1.2 um across 25,000 interconnects.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Underfill Voiding Screening: Scanning Acoustic Microscopy (C-SAM) acoustic impedance scans verify 100% void-free capillary underfill.",
        style="List Bullet"
    )
    doc_ext.add_paragraph(
        "Known Good Die (KGD) Verification: Full at-speed scan and built-in self-test (BIST) required before thermal compression bonding.",
        style="List Bullet"
    )
    t7 = doc_ext.add_table(rows=4, cols=4)
    style_table(t7)
    t7_data = [
        ("Packaging Stage", "Defect Mechanism", "Metrology Method", "Yield Impact SLA"),
        ("Die-to-Wafer Placement", "Placement drift > 2 um", "Automated Optical Alignment", "Placement yield >= 99.85%"),
        ("Thermal Compression Bonding", "Solder bridging / open joints", "High-Resolution X-ray Topography", "Joint yield >= 99.92%"),
        ("HBM3e Stack Attach", "Underfill delamination", "C-SAM Acoustic Microscopy", "Interposer void rate < 0.05%"),
    ]
    for r_idx, row in enumerate(t7_data):
        for c_idx, val in enumerate(row):
            t7.rows[r_idx].cells[c_idx].text = val
    doc_ext.add_paragraph("Page 7 of 7 | Semiconductor Knowledge Hub | Quality | SharePoint Online")

    doc_ext.save(extended_path)
    print("[Semiconductor] Generated base, copy, edited copy (5 pages), and extended copy (7 pages).")


# ---------------------------------------------------------------------------
# Manifest updates
# ---------------------------------------------------------------------------

def update_manifests():
    # Update HR manifest
    hr_m_path = Path("data/sites/hr/manifest.json")
    if hr_m_path.exists():
        manifest = json.loads(hr_m_path.read_text(encoding="utf-8"))
        has_ext = any(m.get("filename") == "employee-handbook-code-of-conduct (extended copy).docx" for m in manifest)
        if not has_ext:
            manifest.append({
                "artifact_id": "HR-DOC-EXT-001",
                "filename": "employee-handbook-code-of-conduct (extended copy).docx",
                "title": "Employee Handbook - Code of Conduct (Extended Copy)",
                "category": "HR Policies",
                "source_table": "corp.hr.knowledge_assets",
                "source_system": "SharePoint Online",
                "profile_generated_at": datetime.now(timezone.utc).isoformat(),
                "relative_path": "HR Policies/employee-handbook-code-of-conduct (extended copy).docx"
            })
            hr_m_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # Update Manufacturing manifest
    mfg_m_path = Path("data/sites/manufacturing/manifest.json")
    if mfg_m_path.exists():
        manifest = json.loads(mfg_m_path.read_text(encoding="utf-8"))
        has_ext = any(m.get("filename") == "incoming-material-inspection-procedure (extended copy).docx" for m in manifest)
        if not has_ext:
            manifest.append({
                "artifact_id": "MFG-DOC-EXT-001",
                "filename": "incoming-material-inspection-procedure (extended copy).docx",
                "title": "Incoming Material Inspection Procedure (Extended Copy)",
                "category": "Quality Assurance",
                "source_table": "corp.manufacturing.knowledge_assets",
                "source_system": "SharePoint Online",
                "profile_generated_at": datetime.now(timezone.utc).isoformat(),
                "relative_path": "Quality Assurance/incoming-material-inspection-procedure (extended copy).docx"
            })
            mfg_m_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # Update Sales manifest
    sales_m_path = Path("data/sites/sales/manifest.json")
    if sales_m_path.exists():
        manifest = json.loads(sales_m_path.read_text(encoding="utf-8"))
        has_ext = any(m.get("filename") == "discovery-call-guide (extended copy).docx" for m in manifest)
        if not has_ext:
            manifest.append({
                "artifact_id": "SALES-DOC-EXT-001",
                "filename": "discovery-call-guide (extended copy).docx",
                "title": "Discovery Call Guide (Extended Copy)",
                "category": "Sales Playbooks",
                "source_table": "corp.sales.knowledge_assets",
                "source_system": "SharePoint Online",
                "profile_generated_at": datetime.now(timezone.utc).isoformat(),
                "relative_path": "Sales Playbooks/discovery-call-guide (extended copy).docx"
            })
            sales_m_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # Create Semiconductor manifest
    semi_m_path = Path("data/sites/semiconductor/manifest.json")
    semi_manifest = [
        {
            "artifact_id": "SEMI-DOC-001",
            "filename": "defect-analysis-planning-workbook.docx",
            "title": "Defect Analysis: Planning Workbook",
            "category": "Quality",
            "source_table": "caldova_dbx_westus2.arrow_semiconductor.defect_analysis",
            "source_system": "SharePoint Online",
            "profile_generated_at": datetime.now(timezone.utc).isoformat(),
            "relative_path": "Quality/defect-analysis-planning-workbook.docx"
        },
        {
            "artifact_id": "SEMI-DOC-002",
            "filename": "defect-analysis-planning-workbook (copy).docx",
            "title": "Defect Analysis: Planning Workbook (Copy)",
            "category": "Quality",
            "source_table": "caldova_dbx_westus2.arrow_semiconductor.defect_analysis",
            "source_system": "SharePoint Online",
            "profile_generated_at": datetime.now(timezone.utc).isoformat(),
            "relative_path": "Quality/defect-analysis-planning-workbook (copy).docx"
        },
        {
            "artifact_id": "SEMI-DOC-003",
            "filename": "defect-analysis-planning-workbook (edited copy).docx",
            "title": "Defect Analysis: Planning Workbook (Edited Copy)",
            "category": "Quality",
            "source_table": "caldova_dbx_westus2.arrow_semiconductor.defect_analysis",
            "source_system": "SharePoint Online",
            "profile_generated_at": datetime.now(timezone.utc).isoformat(),
            "relative_path": "Quality/defect-analysis-planning-workbook (edited copy).docx"
        },
        {
            "artifact_id": "SEMI-DOC-004",
            "filename": "defect-analysis-planning-workbook (extended copy).docx",
            "title": "Defect Analysis: Planning Workbook (Extended Copy)",
            "category": "Quality",
            "source_table": "caldova_dbx_westus2.arrow_semiconductor.defect_analysis",
            "source_system": "SharePoint Online",
            "profile_generated_at": datetime.now(timezone.utc).isoformat(),
            "relative_path": "Quality/defect-analysis-planning-workbook (extended copy).docx"
        }
    ]
    semi_m_path.write_text(json.dumps(semi_manifest, indent=2) + "\n", encoding="utf-8")
    print("Manifests updated.")


# ---------------------------------------------------------------------------
# SharePoint Uploader
# ---------------------------------------------------------------------------

def ensure_drive_folder(token: str, drive_id: str, folder_path: str):
    """Ensure remote folder exists on the drive."""
    segments = [s for s in folder_path.replace("\\", "/").split("/") if s]
    current_segments = []
    for seg in segments:
        parent_encoded = "/" + "/".join(urllib.parse.quote(s) for s in current_segments) if current_segments else ""
        parent_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:{parent_encoded}:/children" if parent_encoded else f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
        current_segments.append(seg)
        current_encoded = "/" + "/".join(urllib.parse.quote(s) for s in current_segments)
        check_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:{current_encoded}"
        req = urllib.request.Request(check_url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req) as resp:
                pass
        except urllib.error.HTTPError as e:
            if e.code == 404:
                body = json.dumps({"name": seg, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}).encode("utf-8")
                create_req = urllib.request.Request(
                    parent_url,
                    data=body,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    method="POST"
                )
                try:
                    with urllib.request.urlopen(create_req) as resp:
                        pass
                except urllib.error.HTTPError as ce:
                    if ce.code != 409:  # Ignore conflict if already created
                        pass


def upload_file_to_graph(token: str, drive_id: str, remote_path: str, local_path: Path):
    folder = os.path.dirname(remote_path.replace("\\", "/"))
    if folder:
        ensure_drive_folder(token, drive_id, folder)

    encoded_path = "/".join(urllib.parse.quote(seg) for seg in remote_path.replace("\\", "/").split("/"))
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{encoded_path}:/content"
    with open(local_path, "rb") as f:
        data = f.read()

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream"
        },
        method="PUT"
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req) as resp:
                res = json.loads(resp.read())
                return res
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                import time; time.sleep(2 ** (attempt + 1))
                continue
            err_content = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Upload of {remote_path} failed (HTTP {e.code}): {err_content}")


def set_list_item_fields(token: str, drive_id: str, item_id: str, site_tag: str, title: str, doc_type: str, category: str):
    """Set basic governance and identity fields on the list item for the drive item."""
    try:
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/listItem"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as resp:
            list_item = json.loads(resp.read())
        list_item_id = list_item.get("id")
        if not list_item_id:
            return

        patch_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/listItem/fields"
        body = {
            "Title": title,
            "ArtifactId": f"ART-{site_tag.upper()}-{list_item_id}",
            "DocumentType": doc_type,
            "KnowledgeCategory": category,
            "DocumentIteration": "Approved",
            "LifecycleStatus": "Published",
            "Authoritative": True,
            "SourceSystem": "SharePoint Online"
        }
        patch_req = urllib.request.Request(
            patch_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="PATCH"
        )
        with urllib.request.urlopen(patch_req) as resp:
            pass
    except Exception as e:
        print(f"    [Warning: listItem metadata update] {e}")


def upload_all_to_sharepoint():
    token = get_graph_token()

    drives = {
        "hr": ("b!AL6sX_MAxk6n_QjT-xFNkAUOXL70j8tEu24Iop-5z6plbSV1d46XSpy0EUHrJ_Ws", "HR"),
        "manufacturing": ("b!uA-v8fGib0GozgOgwl-VwQUOXL70j8tEu24Iop-5z6plbSV1d46XSpy0EUHrJ_Ws", "MANUFACTURING"),
        "sales": ("b!oAB2x1j4XkaUBzvrqdKpWAUOXL70j8tEu24Iop-5z6plbSV1d46XSpy0EUHrJ_Ws", "SALES"),
        "semiconductor_knowledge": ("b!IdZg3_cOw0yTcwcKftzN_kA0vYEvtfJEpbTpkXnbs83WQGHpS4fETbMbrlsPnkBC", "SEMICONDUCTOR"),
        "semiconductor_docs": ("b!IdZg3_cOw0yTcwcKftzN_kA0vYEvtfJEpbTpkXnbs81K4OiCmXS5T4t3VqFo5Q4c", "SEMICONDUCTOR"),
    }

    files_to_upload = [
        # HR
        ("hr", "HR Policies/employee-handbook-code-of-conduct.docx", Path("data/sites/hr/HR Policies/employee-handbook-code-of-conduct.docx"), "Employee Handbook - Code of Conduct", "Policy", "HR Policies"),
        ("hr", "HR Policies/employee-handbook-code-of-conduct (copy).docx", Path("data/sites/hr/HR Policies/employee-handbook-code-of-conduct (copy).docx"), "Employee Handbook - Code of Conduct (Copy)", "Policy", "HR Policies"),
        ("hr", "HR Policies/employee-handbook-code-of-conduct (edited copy).docx", Path("data/sites/hr/HR Policies/employee-handbook-code-of-conduct (edited copy).docx"), "Employee Handbook - Code of Conduct (Edited Copy)", "Policy", "HR Policies"),
        ("hr", "HR Policies/employee-handbook-code-of-conduct (extended copy).docx", Path("data/sites/hr/HR Policies/employee-handbook-code-of-conduct (extended copy).docx"), "Employee Handbook - Code of Conduct (Extended Copy)", "Policy", "HR Policies"),

        # Manufacturing
        ("manufacturing", "Quality Assurance/incoming-material-inspection-procedure.docx", Path("data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure.docx"), "Incoming Material Inspection Procedure", "Procedure", "Quality Assurance"),
        ("manufacturing", "Quality Assurance/incoming-material-inspection-procedure (copy).docx", Path("data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure (copy).docx"), "Incoming Material Inspection Procedure (Copy)", "Procedure", "Quality Assurance"),
        ("manufacturing", "Quality Assurance/incoming-material-inspection-procedure (edited copy).docx", Path("data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure (edited copy).docx"), "Incoming Material Inspection Procedure (Edited Copy)", "Procedure", "Quality Assurance"),
        ("manufacturing", "Quality Assurance/incoming-material-inspection-procedure (extended copy).docx", Path("data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure (extended copy).docx"), "Incoming Material Inspection Procedure (Extended Copy)", "Procedure", "Quality Assurance"),

        # Sales
        ("sales", "Sales Playbooks/discovery-call-guide.docx", Path("data/sites/sales/Sales Playbooks/discovery-call-guide.docx"), "Discovery Call Guide", "Technical Guide", "Sales Playbooks"),
        ("sales", "Sales Playbooks/discovery-call-guide (copy).docx", Path("data/sites/sales/Sales Playbooks/discovery-call-guide (copy).docx"), "Discovery Call Guide (Copy)", "Technical Guide", "Sales Playbooks"),
        ("sales", "Sales Playbooks/discovery-call-guide (edited copy).docx", Path("data/sites/sales/Sales Playbooks/discovery-call-guide (edited copy).docx"), "Discovery Call Guide (Edited Copy)", "Technical Guide", "Sales Playbooks"),
        ("sales", "Sales Playbooks/discovery-call-guide (extended copy).docx", Path("data/sites/sales/Sales Playbooks/discovery-call-guide (extended copy).docx"), "Discovery Call Guide (Extended Copy)", "Technical Guide", "Sales Playbooks"),

        # Semiconductor Knowledge
        ("semiconductor_knowledge", "Quality/defect-analysis-planning-workbook.docx", Path("data/sites/semiconductor/Quality/defect-analysis-planning-workbook.docx"), "Defect Analysis: Planning Workbook", "Specification", "Quality"),
        ("semiconductor_knowledge", "Quality/defect-analysis-planning-workbook (copy).docx", Path("data/sites/semiconductor/Quality/defect-analysis-planning-workbook (copy).docx"), "Defect Analysis: Planning Workbook (Copy)", "Specification", "Quality"),
        ("semiconductor_knowledge", "Quality/defect-analysis-planning-workbook (edited copy).docx", Path("data/sites/semiconductor/Quality/defect-analysis-planning-workbook (edited copy).docx"), "Defect Analysis: Planning Workbook (Edited Copy)", "Specification", "Quality"),
        ("semiconductor_knowledge", "Quality/defect-analysis-planning-workbook (extended copy).docx", Path("data/sites/semiconductor/Quality/defect-analysis-planning-workbook (extended copy).docx"), "Defect Analysis: Planning Workbook (Extended Copy)", "Specification", "Quality"),

        # Also in Semiconductor Documents library
        ("semiconductor_docs", "Quality/defect-analysis-planning-workbook.docx", Path("data/sites/semiconductor/Quality/defect-analysis-planning-workbook.docx"), "Defect Analysis: Planning Workbook", "Specification", "Quality"),
        ("semiconductor_docs", "Quality/defect-analysis-planning-workbook (copy).docx", Path("data/sites/semiconductor/Quality/defect-analysis-planning-workbook (copy).docx"), "Defect Analysis: Planning Workbook (Copy)", "Specification", "Quality"),
        ("semiconductor_docs", "Quality/defect-analysis-planning-workbook (edited copy).docx", Path("data/sites/semiconductor/Quality/defect-analysis-planning-workbook (edited copy).docx"), "Defect Analysis: Planning Workbook (Edited Copy)", "Specification", "Quality"),
        ("semiconductor_docs", "Quality/defect-analysis-planning-workbook (extended copy).docx", Path("data/sites/semiconductor/Quality/defect-analysis-planning-workbook (extended copy).docx"), "Defect Analysis: Planning Workbook (Extended Copy)", "Specification", "Quality"),
    ]

    print(f"Uploading {len(files_to_upload)} files to SharePoint across the 4 sites...")
    for drive_key, rel_path, local_path, title, doc_type, category in files_to_upload:
        drive_id, site_tag = drives[drive_key]
        item = upload_file_to_graph(token, drive_id, rel_path, local_path)
        item_id = item.get("id")
        set_list_item_fields(token, drive_id, item_id, site_tag, title, doc_type, category)
        # Check in the item so it is not left in checked-out state
        try:
            checkin_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/checkin"
            checkin_req = urllib.request.Request(
                checkin_url,
                data=json.dumps({"comment": "Automated governance check-in"}).encode("utf-8"),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(checkin_req) as checkin_resp:
                pass
        except Exception:
            pass  # Already checked in or not supported
        print(f"  [Uploaded & Checked-in] {drive_key} -> {rel_path} (ID: {item_id}, Size: {item.get('size')} bytes)")

    print("All uploads and metadata assignments completed successfully.")


# ---------------------------------------------------------------------------
# Analysis & Comparison Report
# ---------------------------------------------------------------------------

def run_analysis_report():
    sites = [
        {
            "site_id": "hr",
            "site_name": "HR Knowledge Hub",
            "site_url": "https://caldova37587778.sharepoint.com/sites/hrknowledgehub",
            "library": "Documents",
            "folder": "HR Policies",
            "base_file": "data/sites/hr/HR Policies/employee-handbook-code-of-conduct.docx",
            "copy_file": "data/sites/hr/HR Policies/employee-handbook-code-of-conduct (copy).docx",
            "edited_file": "data/sites/hr/HR Policies/employee-handbook-code-of-conduct (edited copy).docx",
            "extended_file": "data/sites/hr/HR Policies/employee-handbook-code-of-conduct (extended copy).docx",
        },
        {
            "site_id": "manufacturing",
            "site_name": "Manufacturing Knowledge Hub",
            "site_url": "https://caldova37587778.sharepoint.com/sites/manufacturingknowledgehub",
            "library": "Documents",
            "folder": "Quality Assurance",
            "base_file": "data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure.docx",
            "copy_file": "data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure (copy).docx",
            "edited_file": "data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure (edited copy).docx",
            "extended_file": "data/sites/manufacturing/Quality Assurance/incoming-material-inspection-procedure (extended copy).docx",
        },
        {
            "site_id": "sales",
            "site_name": "Sales & Marketing Knowledge Hub",
            "site_url": "https://caldova37587778.sharepoint.com/sites/salesmarketingknowledgehub",
            "library": "Documents",
            "folder": "Sales Playbooks",
            "base_file": "data/sites/sales/Sales Playbooks/discovery-call-guide.docx",
            "copy_file": "data/sites/sales/Sales Playbooks/discovery-call-guide (copy).docx",
            "edited_file": "data/sites/sales/Sales Playbooks/discovery-call-guide (edited copy).docx",
            "extended_file": "data/sites/sales/Sales Playbooks/discovery-call-guide (extended copy).docx",
        },
        {
            "site_id": "semiconductor",
            "site_name": "Semiconductor Knowledge Hub",
            "site_url": "https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub",
            "library": "Semiconductor Knowledge",
            "folder": "Quality",
            "base_file": "data/sites/semiconductor/Quality/defect-analysis-planning-workbook.docx",
            "copy_file": "data/sites/semiconductor/Quality/defect-analysis-planning-workbook (copy).docx",
            "edited_file": "data/sites/semiconductor/Quality/defect-analysis-planning-workbook (edited copy).docx",
            "extended_file": "data/sites/semiconductor/Quality/defect-analysis-planning-workbook (extended copy).docx",
        },
    ]

    report = {"sites": []}

    for site in sites:
        base_pages = extract_pages_from_docx(site["base_file"])
        base_text = "\n".join(p["text"] for p in base_pages)
        base_page_count = len(base_pages)

        # 1. Exact Copy
        copy_pages = extract_pages_from_docx(site["copy_file"])
        copy_text = "\n".join(p["text"] for p in copy_pages)
        copy_sim = calculate_similarity(base_text, copy_text)

        # 2. Edited Copy (same page count, few pages different)
        edited_pages = extract_pages_from_docx(site["edited_file"])
        edited_text = "\n".join(p["text"] for p in edited_pages)
        edited_sim = calculate_similarity(base_text, edited_text)
        edited_diff_pages = []
        edited_same_pages = []
        edited_diff_details = []

        for p_idx in range(max(len(base_pages), len(edited_pages))):
            p_num = p_idx + 1
            b_p = base_pages[p_idx]["text"] if p_idx < len(base_pages) else ""
            e_p = edited_pages[p_idx]["text"] if p_idx < len(edited_pages) else ""
            p_sim = calculate_similarity(b_p, e_p)
            if b_p == e_p:
                edited_same_pages.append(p_num)
            else:
                edited_diff_pages.append(p_num)
                edited_diff_details.append({
                    "page_number": p_num,
                    "page_similarity": p_sim,
                    "base_text": b_p,
                    "duplicate_text": e_p,
                })

        # 3. Extended Copy (one or two more pages, differences in few pages)
        ext_pages = extract_pages_from_docx(site["extended_file"])
        ext_text = "\n".join(p["text"] for p in ext_pages)
        ext_sim = calculate_similarity(base_text, ext_text)
        ext_diff_pages = []
        ext_same_pages = []
        ext_diff_details = []

        for p_idx in range(max(len(base_pages), len(ext_pages))):
            p_num = p_idx + 1
            b_p = base_pages[p_idx]["text"] if p_idx < len(base_pages) else ""
            x_p = ext_pages[p_idx]["text"] if p_idx < len(ext_pages) else ""
            p_sim = calculate_similarity(b_p, x_p)
            if b_p == x_p:
                ext_same_pages.append(p_num)
            else:
                is_extra = p_idx >= len(base_pages)
                ext_diff_pages.append(p_num)
                ext_diff_details.append({
                    "page_number": p_num,
                    "is_extra_page": is_extra,
                    "page_similarity": p_sim,
                    "base_text": b_p if not is_extra else "[PAGE DOES NOT EXIST IN BASE DOCUMENT]",
                    "duplicate_text": x_p,
                })

        site_result = {
            "site_id": site["site_id"],
            "site_name": site["site_name"],
            "site_url": site["site_url"],
            "library": site["library"],
            "folder": site["folder"],
            "base_file": Path(site["base_file"]).name,
            "base_page_count": base_page_count,
            "duplicates": [
                {
                    "type": "Exact Copy",
                    "filename": Path(site["copy_file"]).name,
                    "page_count": len(copy_pages),
                    "page_difference": 0,
                    "overall_similarity_percentage": copy_sim,
                    "different_pages": [],
                    "identical_pages": list(range(1, base_page_count + 1)),
                    "differences": []
                },
                {
                    "type": "Near Duplicate (Edits on 2 Pages)",
                    "filename": Path(site["edited_file"]).name,
                    "page_count": len(edited_pages),
                    "page_difference": 0,
                    "overall_similarity_percentage": edited_sim,
                    "different_pages": edited_diff_pages,
                    "identical_pages": edited_same_pages,
                    "differences": edited_diff_details
                },
                {
                    "type": "Extended Duplicate (+2 Pages, Edits on 3 Pages)",
                    "filename": Path(site["extended_file"]).name,
                    "page_count": len(ext_pages),
                    "page_difference": len(ext_pages) - base_page_count,
                    "overall_similarity_percentage": ext_sim,
                    "different_pages": ext_diff_pages,
                    "identical_pages": ext_same_pages,
                    "differences": ext_diff_details
                }
            ]
        }
        report["sites"].append(site_result)

    out_path = Path(".state/cross-site-duplicate-analysis.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report saved to {out_path}.")
    return report


def main():
    print("=== Step 1: Generating Documents per Site ===")
    generate_manufacturing_docs()
    generate_sales_docs()
    generate_hr_docs()
    generate_semiconductor_docs()

    print("\n=== Step 2: Updating Manifests ===")
    update_manifests()

    print("\n=== Step 3: Uploading to SharePoint ===")
    upload_all_to_sharepoint()

    print("\n=== Step 4: Running Duplicate Analysis & Similarity Calculation ===")
    report = run_analysis_report()

    print("\n=== Summary Overview ===")
    for s in report["sites"]:
        print(f"\n--- Site: {s['site_name']} ({s['site_id']}) ---")
        print(f"Base: {s['base_file']} ({s['base_page_count']} pages)")
        for d in s["duplicates"]:
            print(f"  * [{d['type']}] {d['filename']}")
            print(f"    Pages: {d['page_count']} (Delta: {d['page_difference']:+d})")
            print(f"    Similarity: {d['overall_similarity_percentage']}%")
            print(f"    Different Pages: {d['different_pages']}")
            print(f"    Identical Pages: {d['identical_pages']}")


if __name__ == "__main__":
    main()

