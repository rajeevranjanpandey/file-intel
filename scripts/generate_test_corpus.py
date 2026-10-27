#!/usr/bin/env python3
"""
Generate a comprehensive dummy test corpus for testing both:
1. 'Same content' (duplicate text grouping)
2. 'Content topic' (semantic NLP clustering across formats)

Contains:
- 11 distinct file extensions (.pdf, .txt, .md, .csv, .json, .html, .docx, .xlsx, .pptx, .eml, .png)
- 4 PDFs sharing the same financial audit & revenue context
- Multiple semantic clusters (Finance/Audit, NLP/AI, Cooking/Culinary)
"""

import textwrap
import json
from pathlib import Path
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from PIL import Image, ImageDraw, ImageFont

def make_pdf(lines, dest_path):
    """Generate a clean, standard-compliant PDF-1.4 file with text stream."""
    # Td is relative: using it with absolute coordinates pushes text off-page.
    wrapped = [part for line in lines for part in textwrap.wrap(line, width=84)]
    if len(wrapped) > 43:
        raise ValueError("Sample PDF exceeds one page; split the input first")
    stream_content = [b"BT /F1 10 Tf"]
    for i, line in enumerate(wrapped):
        clean_line = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream_content.append(f"1 0 0 1 50 {740 - i * 16} Tm ({clean_line}) Tj".encode('latin-1', 'replace'))
    stream_content.append(b"ET")
    content = b"\n".join(stream_content)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
    ]

    data = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    offset = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(f"{o:010} 00000 n \n".encode() for o in offsets[1:])
    data += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(offset).encode() + b"\n%%EOF"
    dest_path.write_bytes(data)

def generate_corpus(target_dir):
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------
    # CONTEXT A: Financial Audit & Revenue Reconciliation
    # -------------------------------------------------------------
    audit_text = [
        "ANNUAL FINANCIAL AUDIT AND REVENUE RECONCILIATION REPORT 2026",
        "The accounting and finance department conducted a comprehensive review of all quarterly accounts.",
        "Total reconciled revenue reached 1450000 AED against operational expenditures of 820000 AED.",
        "Bank statements, supplier purchase orders, and accounts payable ledgers have been verified.",
        "All corporate tax provisions and financial compliance obligations meet regulatory standards."
    ]

    # 1-4: Four PDFs with the same context
    # PDF 1: Primary audit report
    make_pdf(audit_text, target / "financial_audit_2026.pdf")

    # PDF 2: Exact identical content (for Same Content duplicate grouping)
    make_pdf(audit_text, target / "financial_audit_2026_copy.pdf")

    # PDF 3: Revised audit report (same context with minor wording change)
    revised_text = list(audit_text)
    revised_text[2] = "Total reconciled revenue reached 1450000 AED with verified net margins of 630000 AED."
    make_pdf(revised_text, target / "financial_audit_2026_revised.pdf")

    # PDF 4: Executive summary (same context)
    summary_text = [
        "EXECUTIVE SUMMARY: FINANCIAL AUDIT AND REVENUE RECONCILIATION 2026",
        "Key Findings: Operational expenditures held steady at 820000 AED while gross revenue exceeded target.",
        "All supplier invoice payments, balance sheets, and audit trails have been fully reconciled."
    ]
    make_pdf(summary_text, target / "financial_audit_2026_executive_summary.pdf")

    # 5. .txt (Plain Text - Financial Context)
    (target / "financial_ledger_notes.txt").write_text(
        "Financial Ledger Reconciliation Notes\n"
        "Department: Corporate Accounting\n"
        "Status: Invoices verified against supplier receipts. Approved payments scheduled for release.\n"
        "Audit compliance reference: AUDIT-2026-FIN-091.\n"
    )

    # 6. .csv (CSV Tabular Data - Financial Context)
    (target / "quarterly_budget_breakdown.csv").write_text(
        "Quarter,Revenue_AED,Expenses_AED,Net_Profit_AED\n"
        "Q1,340000,195000,145000\n"
        "Q2,360000,205000,155000\n"
        "Q3,370000,210000,160000\n"
        "Q4,380000,210000,170000\n"
    )

    # 7. .xlsx (Excel Spreadsheet - Financial Context)
    wb = Workbook()
    ws = wb.active
    ws.title = "Audit Balance Sheet"
    ws.append(["Account Code", "Description", "Debit_AED", "Credit_AED"])
    ws.append(["1010", "Cash and Bank Balances", 450000, 0])
    ws.append(["2010", "Accounts Payable - Suppliers", 0, 180000])
    ws.append(["4010", "Operating Revenue", 0, 1450000])
    ws.append(["5010", "Administrative Expenses", 820000, 0])
    wb.save(target / "financial_accounts_payable.xlsx")

    # 8. .eml (Email RFC822 - Financial Context)
    (target / "supplier_payment_confirmation.eml").write_text(
        "From: accounting@enterprise.test\n"
        "To: finance-director@enterprise.test\n"
        "Subject: Audit Confirmation: Supplier Invoice Payments Reconciled\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=utf-8\n\n"
        "Dear Finance Team,\n\n"
        "The annual financial audit has confirmed that all supplier invoices and ledger reconciliations\n"
        "for fiscal year 2026 are approved and within budget allocations.\n\n"
        "Regards,\nAccounting Department\n"
    )

    # 9. .png (Image with OCR Text - Financial Context)
    img = Image.new('RGB', (1400, 450), color='white')
    draw = ImageDraw.Draw(img)
    font_path = Path('/System/Library/Fonts/Supplemental/Arial.ttf')
    font = ImageFont.truetype(str(font_path), 32) if font_path.exists() else ImageFont.load_default()
    draw.text(
        (40, 60),
        "OFFICIAL AUDIT RECEIPT - VENDOR RECONCILIATION\n"
        "Fiscal Year: 2026 | Currency: AED\n"
        "Total Reconciled Amount: 1,450,000 AED\n"
        "Status: Approved and Audited",
        fill='black',
        font=font,
        spacing=24
    )
    img.save(target / "scanned_receipt_slip.png")

    # -------------------------------------------------------------
    # CONTEXT B: Natural Language Processing / AI Engineering
    # -------------------------------------------------------------

    # 10. .docx (Word Document - NLP Context)
    doc = Document()
    doc.add_heading("Semantic Embedding and Clustering Architecture", 0)
    doc.add_paragraph(
        "Natural language processing systems utilize sentence transformers to map variable-length "
        "text into high-dimensional dense vector spaces. Unsupervised clustering algorithms such as "
        "HDBSCAN group semantically related documents using cosine similarity metrics."
    )
    doc.save(target / "nlp_embeddings_research.docx")

    # 11. .pptx (PowerPoint Presentation - NLP Context)
    ppt = Presentation()
    slide = ppt.slides.add_slide(ppt.slide_layouts[1])
    slide.shapes.title.text = "Transformer Neural Architectures"
    slide.placeholders[1].text = (
        "Multi-head self-attention mechanisms enable deep contextual text understanding. "
        "Vector representations support semantic search, automatic document organization, and topic discovery."
    )
    ppt.save(target / "ai_transformer_architecture.pptx")

    # 12. .json (JSON Structured Data - NLP Context)
    (target / "model_hyperparameters.json").write_text(json.dumps({
        "pipeline": "semantic-clustering",
        "embedding_model": "all-MiniLM-L6-v2",
        "dimension": 384,
        "clustering_algorithm": "HDBSCAN",
        "min_cluster_size": 3,
        "distance_metric": "cosine"
    }, indent=2))

    # -------------------------------------------------------------
    # CONTEXT C: Culinary Arts & Cooking Recipes
    # -------------------------------------------------------------

    # 13. .md (Markdown Document - Culinary Context)
    (target / "recipe_italian_culinary_guide.md").write_text(
        "# Artisanal Italian Culinary Guide\n\n"
        "## Tomato Basil Fettuccine\n\n"
        "Boil freshly prepared fettuccine in salted water until al dente. In a heavy skillet, "
        "saute crushed garlic cloves in extra virgin olive oil, add San Marzano tomatoes, and simmer gently. "
        "Garnish with fresh basil leaves and aged parmesan cheese.\n"
    )

    # 14. .html (HTML Web Page - Culinary Context)
    (target / "restaurant_menu_operations.html").write_text(
        "<!DOCTYPE html>\n<html>\n<head><title>Kitchen Operations and Menu</title></head>\n"
        "<body>\n"
        "  <h1>Mediterranean Vegetable Medley</h1>\n"
        "  <p>Fresh seasonal vegetables roasted with rosemary, thyme, garlic, and cold-pressed olive oil.</p>\n"
        "  <p>Served warm with freshly baked sourdough bread and garlic dipping sauce.</p>\n"
        "</body>\n</html>\n"
    )

    print(f"Successfully generated {len(list(target.iterdir()))} test files in: {target}")

if __name__ == "__main__":
    generate_corpus(Path("dummy_test_corpus"))
    generate_corpus(Path("demo/dummy_test_corpus"))
