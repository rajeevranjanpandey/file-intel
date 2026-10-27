#!/usr/bin/env python3
import textwrap
import json
from pathlib import Path

def make_pdf(lines, dest_path):
    """Zero-dependency standard PDF-1.4 generator."""
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

def setup_directory(base_dir):
    target = Path(base_dir)
    target.mkdir(parents=True, exist_ok=True)

    # Context 1: Financial Audit & Revenue Reconciliation
    audit_text = [
        "ANNUAL FINANCIAL AUDIT AND REVENUE RECONCILIATION REPORT 2026",
        "The accounting and finance department conducted a comprehensive review of all quarterly accounts.",
        "Total reconciled revenue reached 1450000 AED against operational expenditures of 820000 AED.",
        "Bank statements supplier purchase orders and accounts payable ledgers have been verified.",
        "All corporate tax provisions and financial compliance obligations meet regulatory standards."
    ]

    # --- 4 PDFs WITH THE SAME CONTEXT ---
    # PDF 1: Primary audit report
    make_pdf(audit_text, target / "audit_report_v1.pdf")

    # PDF 2: Exact identical content (Validates 'Same content' / duplicate grouping)
    make_pdf(audit_text, target / "audit_report_v2_exact_copy.pdf")

    # PDF 3: Revised audit report (Same topic & context, minor update for semantic grouping)
    revised_text = list(audit_text)
    revised_text[2] = "Total reconciled revenue reached 1450000 AED with verified net operating margin."
    make_pdf(revised_text, target / "audit_report_v3_revised.pdf")

    # PDF 4: Executive summary (Same topic & context)
    summary_text = [
        "EXECUTIVE SUMMARY: FINANCIAL AUDIT AND REVENUE RECONCILIATION 2026",
        "Key Findings: Operational expenditures held steady at 820000 AED while revenue met target.",
        "All supplier invoice payments balance sheets and audit trails have been fully reconciled."
    ]
    make_pdf(summary_text, target / "audit_report_v4_executive_summary.pdf")

    # --- 10+ DIFFERENT FILE TYPES ---
    # 1. Plain Text (.txt) - Financial context
    (target / "financial_ledger_notes.txt").write_text(
        "Financial Ledger Reconciliation Notes\n"
        "Department: Corporate Accounting\n"
        "Status: Invoices verified against supplier receipts. Approved payments scheduled for release.\n"
        "Audit compliance reference: AUDIT-2026-FIN-091.\n"
    )

    # 2. Markdown (.md) - Culinary / Recipe context (Distinct cluster)
    (target / "recipe_italian_culinary_guide.md").write_text(
        "# Artisanal Italian Culinary Guide\n\n"
        "## Tomato Basil Fettuccine\n\n"
        "Boil freshly prepared fettuccine in salted water until al dente. In a heavy skillet, "
        "saute crushed garlic cloves in extra virgin olive oil, add San Marzano tomatoes, and simmer gently. "
        "Garnish with fresh basil leaves and aged parmesan cheese.\n"
    )

    # 3. CSV Spreadsheet (.csv) - Financial context
    (target / "quarterly_budget_breakdown.csv").write_text(
        "Quarter,Revenue_AED,Expenses_AED,Net_Profit_AED\n"
        "Q1,340000,195000,145000\n"
        "Q2,360000,205000,155000\n"
        "Q3,370000,210000,160000\n"
        "Q4,380000,210000,170000\n"
    )

    # 4. JSON Data (.json) - NLP / AI context (Distinct cluster)
    (target / "model_hyperparameters.json").write_text(json.dumps({
        "pipeline": "semantic-clustering",
        "embedding_model": "all-MiniLM-L6-v2",
        "dimension": 384,
        "clustering_algorithm": "HDBSCAN",
        "min_cluster_size": 3,
        "distance_metric": "cosine"
    }, indent=2))

    # 5. HTML Document (.html) - Culinary context
    (target / "restaurant_menu_operations.html").write_text(
        "<!DOCTYPE html>\n<html>\n<head><title>Kitchen Operations and Menu</title></head>\n"
        "<body>\n"
        "  <h1>Mediterranean Vegetable Medley</h1>\n"
        "  <p>Fresh seasonal vegetables roasted with rosemary, thyme, garlic, and cold-pressed olive oil.</p>\n"
        "  <p>Served warm with freshly baked sourdough bread and garlic dipping sauce.</p>\n"
        "</body>\n</html>\n"
    )

    # 6. Email Message (.eml) - Financial context
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

    # 7. Word Document (.docx) - NLP / AI context
    demo_formats = Path("demo/formats")
    if (demo_formats / "research.docx").exists():
        (target / "nlp_embeddings_research.docx").write_bytes((demo_formats / "research.docx").read_bytes())

    # 8. Excel Workbook (.xlsx) - Financial context
    if (demo_formats / "ledger.xlsx").exists():
        (target / "financial_accounts_payable.xlsx").write_bytes((demo_formats / "ledger.xlsx").read_bytes())

    # 9. PowerPoint Presentation (.pptx) - NLP / AI context
    if (demo_formats / "search.pptx").exists():
        (target / "ai_transformer_architecture.pptx").write_bytes((demo_formats / "search.pptx").read_bytes())

    # 10. Scanned Image (.png) - Financial context
    if (demo_formats / "scanned-invoice.png").exists():
        (target / "scanned_receipt_slip.png").write_bytes((demo_formats / "scanned-invoice.png").read_bytes())

    # 11. Zip Archive (.zip) - Archive format
    if (demo_formats / "notes.zip").exists():
        (target / "archived_documents.zip").write_bytes((demo_formats / "notes.zip").read_bytes())

    files = sorted(f.name for f in target.iterdir() if not f.name.startswith('.'))
    print(f"Directory '{target}' created with {len(files)} files:")
    for f in files:
        print(f"  - {f}")

if __name__ == '__main__':
    setup_directory("dummy_test_corpus")
    setup_directory("demo/dummy_test_corpus")
