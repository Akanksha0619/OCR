from io import BytesIO

from docx import Document

from app.services.docx_service import DocxService
from app.services.information_extraction_service import InformationExtractionService
from app.utils.file_validation import DocumentFormat, detect_format, validate_upload


def make_docx() -> bytes:
    document = Document()
    document.add_paragraph("Akanksha Marathe")
    document.add_paragraph("Email: akanksha@example.com")
    document.add_paragraph("PROFESSIONAL SUMMARY")
    document.add_paragraph("Python backend developer")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Skill"
    table.cell(0, 1).text = "Level"
    table.cell(1, 0).text = "Python"
    table.cell(1, 1).text = "Advanced"
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_signature_and_validation():
    data = make_docx()
    assert detect_format(data) is DocumentFormat.DOCX
    upload = validate_upload("resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", data)
    assert upload.format is DocumentFormat.DOCX


def test_docx_extracts_paragraphs_and_tables():
    text, tables = DocxService().extract(make_docx())
    assert "Akanksha Marathe" in text
    assert tables == [{"table_number": 1, "headers": ["Skill", "Level"], "rows": [["Python", "Advanced"]]}]


def test_resume_classification_and_basic_fields():
    text = """Akanksha Marathe
Email: akanksha@example.com
PROFESSIONAL SUMMARY
Python Backend Developer
TECHNICAL SKILLS
Python, FastAPI
WORK EXPERIENCE
Backend Developer at Example
EDUCATION
B.Tech"""
    result = InformationExtractionService().extract(text)
    assert result["document_type"] == "resume"
    assert result["resume"]["name"] == "Akanksha Marathe"
    assert result["resume"]["email"] == "akanksha@example.com"
    assert "technical_skills" in result["resume"]["sections"]


def test_invoice_fields_are_extracted_without_inventing_missing_values():
    result = InformationExtractionService().extract("INVOICE\nInvoice No: INV-1024\nInvoice Date: 24-11-2026\nTotal: INR 5,000")
    assert result["document_type"] == "invoice"
    assert result["invoice"]["invoice_number"] == "INV-1024"
    assert result["invoice"]["invoice_date"] == "24-11-2026"
    assert result["invoice"]["due_date"] is None


def test_bank_statement_transactions_are_mapped_from_detected_tables():
    text = "BANK STATEMENT\nAccount Number: 1234567890"
    tables = [{"headers": ["Date", "Description", "Debit", "Credit", "Balance"], "rows": [["01-01-2026", "ATM", "500", "", "9500"]]}]
    result = InformationExtractionService().extract(text, tables)
    assert result["document_type"] == "bank_statement"
    assert result["bank_statement"]["transactions"][0]["description"] == "ATM"
