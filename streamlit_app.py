"""Streamlit UI for the OCR Document Extraction API.

Run the FastAPI backend separately, then launch:
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Document Intelligence | OCR",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE_URL = os.getenv("OCR_API_URL", "http://127.0.0.1:8000").rstrip("/")
EXTRACT_URL = f"{API_BASE_URL}/api/v1/ocr/extract"
HEALTH_URL = f"{API_BASE_URL}/api/v1/health"

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1450px;}
      .hero {padding: 1.35rem 1.5rem; border: 1px solid rgba(128,128,128,.25);
             border-radius: 16px; margin-bottom: 1rem;}
      .muted {color: #858b98; font-size: .92rem;}
      div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.2);
          padding: 12px; border-radius: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📄 Document Intelligence")
st.caption("Upload a document. OCR extracts its information and automatically prepares an editable form.")

with st.sidebar:
    st.header("Connection")
    st.write("**OCR API**")
    st.code(API_BASE_URL, language=None)
    try:
        health = requests.get(HEALTH_URL, timeout=4)
        if health.ok:
            st.success("Backend is reachable")
        else:
            st.warning(f"Backend responded with HTTP {health.status_code}")
    except requests.RequestException:
        st.error("Backend is not reachable")
        st.caption("Start FastAPI before uploading a document.")
    st.divider()
    st.subheader("Supported files")
    st.write("PDF · DOCX · PNG · JPG · JPEG · TIFF · BMP · WEBP")
    st.caption("The API applies its own upload, page and image-size validation.")
    st.divider()
    st.caption("Extracted fields are best-effort. Always verify important information before saving.")

st.markdown(
    """
    <div class="hero">
      <h3 style="margin:0 0 .35rem 0">Upload and extract</h3>
      <div class="muted">Your document is sent to the existing FastAPI service. The service returns OCR text,
      document classification, structured fields and detected tables.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

uploaded = st.file_uploader(
    "Choose a document",
    type=["pdf", "docx", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"],
    help="Select one supported document. Extraction starts automatically after upload.",
)

def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)

def add_editable_field(label: str, value: Any, key: str, multiline: bool = False) -> str:
    text_value = as_text(value)
    if multiline or "\n" in text_value or len(text_value) > 100:
        return st.text_area(label, value=text_value, key=key, height=110)
    return st.text_input(label, value=text_value, key=key)

def make_form_fields(structured: dict[str, Any]) -> list[tuple[str, str, Any, bool]]:
    """Create human-readable editable fields from the API's structured_data."""
    kind = structured.get("document_type", "general_document")
    section_name = {
        "resume": "resume",
        "invoice": "invoice",
        "bank_statement": "bank_statement",
        "form": "form",
    }.get(kind)
    section = structured.get(section_name, {}) if section_name else {}
    fields: list[tuple[str, str, Any, bool]] = []

    # Common fields are useful across document categories.
    common_fields = [
        ("Emails", "emails", structured.get("emails", []), False),
        ("Phone numbers", "phone_numbers", structured.get("phone_numbers", []), False),
        ("Dates found", "dates", structured.get("dates", []), False),
        ("Monetary values", "monetary_values", structured.get("monetary_values", []), False),
    ]
    fields.extend((label, name, value, multi) for label, name, value, multi in common_fields)

    if isinstance(section, dict):
        for name, value in section.items():
            if name in {"key_value_pairs", "sections", "transactions", "tables_detected"}:
                continue
            label = name.replace("_", " ").strip().title()
            multiline = isinstance(value, list) or isinstance(value, dict) or (
                isinstance(value, str) and ("\n" in value or len(value) > 100)
            )
            fields.append((label, f"{section_name}_{name}", value, multiline))

    # Preserve arbitrary labelled fields detected by the API.
    pairs = structured.get("key_value_pairs", [])
    if isinstance(pairs, list):
        for index, pair in enumerate(pairs):
            if isinstance(pair, dict):
                label = str(pair.get("key") or f"Detected field {index + 1}")
                fields.append((label, f"pair_{index}", pair.get("value", ""), False))

    # Form extraction nests key/value pairs under form.fields.
    if kind == "form" and isinstance(section, dict):
        nested_pairs = section.get("fields", [])
        if isinstance(nested_pairs, list):
            for index, pair in enumerate(nested_pairs):
                if isinstance(pair, dict):
                    label = str(pair.get("key") or f"Form field {index + 1}")
                    fields.append((label, f"form_pair_{index}", pair.get("value", ""), False))

    # Remove duplicate widget keys while retaining the first occurrence.
    seen = set()
    unique = []
    for item in fields:
        if item[1] not in seen:
            seen.add(item[1])
            unique.append(item)
    return unique

def extract_document(file_name: str, file_bytes: bytes) -> dict[str, Any]:
    files = {"file": (file_name, file_bytes)}
    response = requests.post(EXTRACT_URL, files=files, timeout=(10, 360))
    if not response.ok:
        try:
            detail = response.json().get("error", {})
            message = detail.get("message") or response.text
            code = detail.get("code", "request_failed")
        except (ValueError, AttributeError):
            message, code = response.text, "request_failed"
        raise RuntimeError(f"{code}: {message}")
    return response.json()

if uploaded is None:
    st.info("Upload a document to begin. The extracted information will appear in an editable form.")
    st.stop()

file_bytes = uploaded.getvalue()
file_fingerprint = hashlib.sha256(file_bytes).hexdigest()

if st.session_state.get("processed_fingerprint") != file_fingerprint:
    with st.spinner("Processing document and extracting information..."):
        try:
            result = extract_document(uploaded.name, file_bytes)
            st.session_state["ocr_result"] = result
            st.session_state["processed_fingerprint"] = file_fingerprint
            st.session_state["reviewed_data"] = None
            # Clear prior widget values so the new document populates the new form.
            for state_key in list(st.session_state.keys()):
                if state_key.startswith("field_"):
                    del st.session_state[state_key]
        except requests.ConnectionError:
            st.error("Could not connect to the OCR API. Check that FastAPI is running and OCR_API_URL is correct.")
            st.stop()
        except requests.Timeout:
            st.error("The extraction request timed out. Try a smaller document or increase the client timeout.")
            st.stop()
        except Exception as exc:
            st.error(f"Document extraction failed: {exc}")
            st.stop()

result = st.session_state.get("ocr_result")
if not result:
    st.stop()

structured = result.get("structured_data") or {}
metadata = result.get("metadata") or {}
doc_kind = structured.get("document_type", "general_document")
status = result.get("status", "unknown")

st.divider()
st.subheader("Extraction summary")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Document type", str(doc_kind).replace("_", " ").title())
m2.metric("Pages", result.get("total_pages", 0))
m3.metric("OCR pages", metadata.get("ocr_pages", 0))
m4.metric("Processing time", f'{metadata.get("processing_time_ms", 0)} ms')

if status == "success":
    st.success(f"Extraction completed: {result.get('filename', uploaded.name)}")
elif status == "partial":
    st.warning("Extraction completed with some page failures. Review the page results and extracted fields.")
else:
    st.error(f"Extraction status: {status}")

pages = result.get("pages", [])
with st.expander("Page-by-page processing details", expanded=False):
    for page in pages:
        confidence = page.get("confidence")
        confidence_text = f"{confidence:.1f}%" if isinstance(confidence, (int, float)) else "Not provided"
        st.markdown(
            f"**Page {page.get('page_number')}** · Method: `{page.get('method')}` · "
            f"Status: `{page.get('status')}` · Confidence: `{confidence_text}`"
        )
        if page.get("preprocessing_applied"):
            st.caption("Preprocessing: " + ", ".join(page["preprocessing_applied"]))
        if page.get("error"):
            st.warning(page["error"])

st.divider()
st.subheader("Review and edit extracted information")
st.caption("Fields below are prefilled from structured_data. Correct any OCR mistakes before exporting.")

fields = make_form_fields(structured)
if not fields:
    st.info("No structured fields were detected. You can still review and export the raw extracted text below.")

with st.form("review_extracted_fields"):
    if fields:
        columns = st.columns(2)
        for index, (label, name, value, multiline) in enumerate(fields):
            with columns[index % 2]:
                add_editable_field(label, value, f"field_{name}", multiline)
    else:
        st.write("No editable structured fields are available for this document.")
    submitted = st.form_submit_button("Save reviewed information", type="primary", use_container_width=True)

if submitted:
    reviewed = {}
    for label, name, original, multiline in fields:
        reviewed[label] = st.session_state.get(f"field_{name}", as_text(original))
    st.session_state["reviewed_data"] = {
        "filename": result.get("filename", uploaded.name),
        "document_type": doc_kind,
        "fields": reviewed,
        "tables": result.get("tables", []),
        "full_text": result.get("full_text", ""),
    }
    st.success("Your reviewed information is ready to export.")

reviewed_data = st.session_state.get("reviewed_data")
if reviewed_data:
    st.download_button(
        "⬇️ Download reviewed data (JSON)",
        data=json.dumps(reviewed_data, ensure_ascii=False, indent=2),
        file_name=f"{os.path.splitext(uploaded.name)[0]}_reviewed.json",
        mime="application/json",
        use_container_width=True,
    )

tables = result.get("tables") or []
if tables:
    st.divider()
    st.subheader("Detected tables")
    for index, table in enumerate(tables, start=1):
        st.markdown(f"**Table {index}**")
        headers = table.get("headers") or []
        rows = table.get("rows") or []
        if headers:
            try:
                st.dataframe(pd.DataFrame(rows, columns=headers), use_container_width=True, hide_index=True)
            except (ValueError, TypeError):
                st.json(table)
        else:
            st.json(table)

with st.expander("View raw OCR text", expanded=False):
    st.text_area("Extracted document text", value=result.get("full_text", ""), height=320, disabled=True)
    st.download_button(
        "Download extracted text",
        data=result.get("full_text", ""),
        file_name=f"{os.path.splitext(uploaded.name)[0]}_ocr.txt",
        mime="text/plain",
    )

with st.expander("View complete API response (JSON)", expanded=False):
    st.json(result)
    st.download_button(
        "Download complete extraction response",
        data=json.dumps(result, ensure_ascii=False, indent=2),
        file_name=f"{os.path.splitext(uploaded.name)[0]}_extraction.json",
        mime="application/json",
    )
