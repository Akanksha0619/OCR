"""Local, explainable document classification and field extraction.

This is deliberately heuristic: it never invents values and returns null/empty
collections when a field cannot be found. It does not use a cloud API or LLM.
"""
from __future__ import annotations

import re
from typing import Any


class InformationExtractionService:
    KEY_VALUE_RE = re.compile(r"^\s*([^:\n]{2,60})\s*:\s*(.*?)\s*$", re.MULTILINE)
    EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
    PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
    DATE_RE = re.compile(r"\b(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\b")
    MONEY_RE = re.compile(r"(?:₹|INR|Rs\.?|\$|USD|€|£)\s?[\d,]+(?:\.\d{1,2})?", re.I)

    def extract(self, text: str, tables: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        clean = text or ""
        kind = self.classify(clean)
        key_values = self._key_values(clean)
        common: dict[str, Any] = {
            "document_type": kind,
            "key_value_pairs": key_values,
            "emails": list(dict.fromkeys(self.EMAIL_RE.findall(clean))),
            "phone_numbers": list(dict.fromkeys(x.strip() for x in self.PHONE_RE.findall(clean))),
            "dates": list(dict.fromkeys(self.DATE_RE.findall(clean))),
            "monetary_values": list(dict.fromkeys(self.MONEY_RE.findall(clean))),
        }
        if kind == "resume":
            common["resume"] = self._resume(clean, key_values)
        elif kind == "invoice":
            common["invoice"] = self._invoice(clean, key_values)
        elif kind == "bank_statement":
            common["bank_statement"] = self._bank_statement(clean, key_values, tables or [])
        elif kind == "form":
            common["form"] = {"fields": key_values, "checkbox_markers": self._checkboxes(clean)}
        else:
            common["general"] = {"headings": self._headings(clean), "paragraph_count": len([p for p in re.split(r"\n\s*\n", clean) if p.strip()])}
        common["tables"] = tables or []
        return common

    @staticmethod
    def classify(text: str) -> str:
        t = text.lower()
        if any(x in t for x in ("resume", "curriculum vitae", "professional summary", "work experience", "technical skills")):
            return "resume"
        if any(x in t for x in ("invoice", "invoice number", "bill to", "subtotal", "amount due")):
            return "invoice"
        if any(x in t for x in ("bank statement", "account statement", "opening balance", "closing balance", "transaction details")):
            return "bank_statement"
        if len(re.findall(r"(?:_{3,}|\.{3,}|\[\s*[xX ]?\s*\])", text)) >= 2 or "please fill" in t:
            return "form"
        return "general_document"

    def _key_values(self, text: str) -> list[dict[str, str]]:
        pairs = []
        for key, value in self.KEY_VALUE_RE.findall(text):
            key, value = key.strip(), value.strip()
            if value and len(key) <= 60:
                pairs.append({"key": key, "value": value})
        return pairs

    def _resume(self, text: str, pairs: list[dict[str, str]]) -> dict[str, Any]:
        lines = [x.strip(" •\t") for x in text.splitlines() if x.strip()]
        email = self.EMAIL_RE.search(text)
        phone = self.PHONE_RE.search(text)
        name = next((x for x in lines[:8] if not self.EMAIL_RE.search(x) and not self.PHONE_RE.search(x) and len(x.split()) <= 5 and not re.search(r"resume|curriculum vitae", x, re.I)), None)
        sections = self._sections(text, ("professional summary", "technical skills", "skills", "work experience", "experience", "projects", "education", "certifications"))
        skill_text = sections.get("technical_skills") or sections.get("skills") or ""
        skills = [part.strip(" •-\t") for part in re.split(r"[,|;\n]", skill_text) if part.strip(" •-\t")]
        return {
            "name": name,
            "email": email.group(0) if email else None,
            "phone": phone.group(0).strip() if phone else None,
            "skills": skills,
            "experience_entries": [x.strip() for x in sections.get("work_experience", sections.get("experience", "")).splitlines() if x.strip()],
            "education_entries": [x.strip() for x in sections.get("education", "").splitlines() if x.strip()],
            "sections": sections,
            "key_value_pairs": pairs,
        }

    def _invoice(self, text: str, pairs: list[dict[str, str]]) -> dict[str, Any]:
        def find(pattern: str) -> str | None:
            m = re.search(pattern, text, re.I | re.M)
            return m.group(1).strip() if m else None
        money = self.MONEY_RE.findall(text)
        return {
            "invoice_number": find(r"invoice\s*(?:no\.?|number|#)\s*[:#-]?\s*([A-Z0-9/-]+)"),
            "invoice_date": find(r"(?:invoice\s*)?date\s*[:#-]?\s*([\d./-]+)"),
            "due_date": find(r"due\s*date\s*[:#-]?\s*([\d./-]+)"),
            "amounts_found": list(dict.fromkeys(money)),
            "key_value_pairs": pairs,
        }

    def _bank_statement(self, text: str, pairs: list[dict[str, str]], tables: list[dict[str, Any]]) -> dict[str, Any]:
        account = re.search(r"(?:account\s*(?:number|no)?|a/c\s*(?:no)?)\s*[:#-]?\s*([Xx*\d -]{4,})", text, re.I)
        transactions = []
        for table in tables:
            headers = [str(x).lower() for x in table.get("headers", [])]
            if any(token in " ".join(headers) for token in ("date", "description", "debit", "credit", "balance")):
                for row in table.get("rows", []):
                    transactions.append({headers[i] if i < len(headers) else f"column_{i + 1}": value for i, value in enumerate(row)})
        return {"account_number_as_printed": account.group(1).strip() if account else None, "transactions": transactions, "tables_detected": len(tables), "key_value_pairs": pairs}

    @staticmethod
    def _checkboxes(text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if re.search(r"(?:☒|☑|☐|\[[xX ]\])", line)]

    @staticmethod
    def _headings(text: str) -> list[str]:
        result = []
        for line in text.splitlines():
            value = line.strip()
            if value and len(value) < 80 and (value.isupper() or value.endswith(":")):
                result.append(value.rstrip(":"))
        return list(dict.fromkeys(result))

    @staticmethod
    def _sections(text: str, names: tuple[str, ...]) -> dict[str, str]:
        lines = text.splitlines()
        found: dict[str, str] = {}
        current = None
        chunks: dict[str, list[str]] = {}
        for line in lines:
            stripped = line.strip().lower().rstrip(":")
            matched = next((n for n in names if stripped == n), None)
            if matched:
                current = matched
                chunks.setdefault(current, [])
            elif current:
                chunks[current].append(line.strip())
        for key, values in chunks.items():
            found[key.replace(" ", "_")] = "\n".join(x for x in values if x)
        return found
