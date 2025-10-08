import re
import pdfplumber
import spacy
from fastapi import FastAPI, UploadFile, File
import uvicorn
import os

app = FastAPI()
nlp = spacy.load("en_core_web_sm")

# Common prefixes
prefixes = ["Mr", "Mrs", "Ms", "Miss", "Dr", "Shri", "Smt", "Sh", "Smt.", "Dr.", "श्री", "श्रीमती"]

# Junk keywords
junk_keywords = {
    "sample collected", "tests done", "lab report", "report", "result", "date", "patient no"
}


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'(.)\1{2,}', r'\1', text)  # reduce repeated chars
    text = re.sub(r"[^\w\s\u0900-\u097F]", "", text)  # remove non-letters
    text = re.sub(r"\s+", " ", text)  # collapse spaces
    return text.strip()


def clean_name(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    raw = normalize_text(raw)

    # Remove age/gender patterns
    raw = re.sub(r"\(?\s*\d{1,3}\s*[Yy]\s*/?\s*[MF]\s*\)?", "", raw)
    raw = re.sub(r"\(?\s*[MF]\s*/?\s*\d{1,3}\s*[Yy]?\s*\)?", "", raw)

    # Cut at unwanted words
    raw = re.split(
        r"\b(DOB|Age|Gender|Sex|MRN|VID|ID|Patient No|UHID|Registration|Tests Done|Sample Collected)\b",
        raw, flags=re.IGNORECASE
    )[0].strip()

    # Remove prefixes
    for p in prefixes:
        raw = re.sub(rf"^\s*{re.escape(p)}\.?\s+", "", raw, flags=re.IGNORECASE)

    # Remove short trailing codes/numbers
    raw = re.sub(
        r"(\bNo\.?\s*[:\-]?\s*\d+\b|\bC\d+\b|\bT\d+\b|\bVID\s*[:\-]?\d+\b|\b\d{1,4}\b)",
        "", raw, flags=re.IGNORECASE
    )

    raw = re.sub(r"\s+", " ", raw).strip()

    # Ignore barcode/hash-like tokens
    if re.fullmatch(r"[A-Z0-9]{8,}", raw):
        return ""

    if raw.lower() in junk_keywords or len(raw.split()) > 6:
        return ""

    return raw


def extract_from_text(text: str) -> str:
    patterns = [
        r"Patient\s*Name\s*[:\-]?\s*([^\n]+)",
        r"Name\s*[:\-]?\s*([^\n]+)",
        r"Patient\s*[:\-]?\s*([^\n]+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = clean_name(match.group(1))
            if candidate:
                return candidate

    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            candidate = clean_name(ent.text)
            if candidate:
                return candidate

    # Heuristic: 2–5 word lines
    for line in text.split("\n"):
        candidate = clean_name(line)
        if 2 <= len(candidate.split()) <= 5:
            return candidate

    return ""


def extract_from_tables(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for table in tables:
                for row in table:
                    for cell in (row or []):
                        if cell:
                            candidate = extract_from_text(cell)
                            if candidate:
                                return candidate
    return ""


def extract_from_filename(file_path: str) -> str:
    base = os.path.basename(file_path or "")
    name_part = os.path.splitext(base)[0]

    parts = [p for p in re.split(r"[_\-]+", name_part) if p]

    # remove numeric IDs
    parts = [p for p in parts if not p.isdigit()]

    # Drop trailing WL/REPORT/RESULT
    if parts and parts[-1].upper() in {"WL", "REPORT", "RESULT"}:
        parts = parts[:-1]

    # Keep only words with letters
    name_tokens = []
    for p in parts:
        cleaned = re.sub(r"[^A-Za-z\u0900-\u097F]", "", p)
        if cleaned and len(cleaned) > 1:
            name_tokens.append(cleaned.capitalize())

    return " ".join(name_tokens)


def extract_patient_name(pdf_path: str, original_filename: str = "") -> (str, str): # type: ignore
    """
    Returns (patient_name, source)
    - AG Diagnostics (filename like 125090547_NAME_WL) → filename only
    - Other labs → try text → tables → filename
    """
    base = os.path.basename(original_filename or pdf_path).lower()
    stem = os.path.splitext(base)[0]

    # ✅ Strict AG Diagnostics rule
    if re.match(r"^\d+_.*_wl$", stem):
        return extract_from_filename(original_filename or pdf_path), "filename"

    # Normal flow
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += normalize_text(page_text) + "\n"

    # 1) Text
    name = extract_from_text(text)
    if name:
        return name, "text"

    # 2) Tables
    name = extract_from_tables(pdf_path)
    if name:
        return name, "tables"

    # 3) Filename fallback
    return extract_from_filename(original_filename or pdf_path), "filename"
