"""
PDF ingestion       — PyMuPDF extracts text, regex + HF parses fields
Edge case detection — local zero-shot-classification model
Email drafting      — HuggingFace Inference API (free tier)
"""

import os
import re
import fitz  # PyMuPDF
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from transformers import pipeline

from flag_human.db import init_db, lookup_shipment

load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")

KNOWN_CODES: dict[str, str] = {
    "SS": "Short shipment",
    "LD": "Late delivery",
    "LB": "Labeling violation",
    "PD": "Price discrepancy",
    "DA": "Damaged goods",
}

HUMAN_REVIEW_THRESHOLD = 500  # dollars

# ── Lazy-loaded models (downloaded once, cached in ~/.cache/huggingface) ──────
_classifier = None


def get_classifier():
    """
    Zero-shot classifier — runs locally on Apple Silicon via MPS.
    Uses facebook/bart-large-mnli (~1.6GB, downloads once).
    """
    global _classifier
    if _classifier is None:
        print("  Loading classification model (first run downloads ~1.6GB)...")
        _classifier = pipeline(
            "zero-shot-classification",
            model="facebook/bart-large-mnli",
            device="mps",  # Apple Silicon GPU — remove if on Intel/Linux
        )
    return _classifier


# ── Step 1: PDF ingestion ─────────────────────────────────────────────────────


def parse_pdf(pdf_path: str) -> dict:
    """
    Extract deduction fields from a remittance advice PDF.

    Strategy:
    1. PyMuPDF pulls raw text
    2. Regex handles the structured fields (PO, code, amount) — fast and reliable
    3. HuggingFace zero-shot classifier confirms/corrects the deduction code
       against known categories as a cross-check

    Returns dict: po_number, deduction_code, deduction_amount, reason_text
    """
    doc = fitz.open(pdf_path)
    raw_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    # Regex extraction — works well for structured remittance formats
    po_match = re.search(r"PO\s*(?:Number|#)?\s*:?\s*(PO-\w+)", raw_text, re.I)
    code_match = re.search(
        r"Deduction\s*Code\s*:?\s*([A-Z]{2,6}(?:-\d+)?)", raw_text, re.I
    )
    amount_match = re.search(
        r"Deduction\s*Amount\s*:?\s*\$?([\d,]+\.?\d*)", raw_text, re.I
    )
    reason_match = re.search(r"Reason\s*:?\s*(.+)", raw_text, re.I)

    extracted = {
        "po_number": po_match.group(1).strip() if po_match else "UNKNOWN",
        "deduction_code": (
            code_match.group(1).strip().upper() if code_match else "UNKNOWN"
        ),
        "deduction_amount": (
            float(amount_match.group(1).replace(",", "")) if amount_match else 0.0
        ),
        "reason_text": (
            reason_match.group(1).strip() if reason_match else raw_text[:200]
        ),
    }

    # HuggingFace cross-check: classify the reason text against known code labels
    # This catches cases where the printed code doesn't match the stated reason
    if extracted["reason_text"] and extracted["reason_text"] != raw_text[:200]:
        clf = get_classifier()
        labels = list(KNOWN_CODES.values()) + ["Other / unknown"]
        result = clf(extracted["reason_text"], candidate_labels=labels)
        top_label = result["labels"][0]
        top_score = result["scores"][0]

        # If classifier is confident (>0.6) and disagrees with extracted code,
        # flag it — don't silently override, surface the discrepancy
        extracted_desc = KNOWN_CODES.get(extracted["deduction_code"], "")
        if top_score > 0.6 and top_label != extracted_desc and extracted_desc:
            extracted["classification_warning"] = (
                f"Code {extracted['deduction_code']} ({extracted_desc}) "
                f"but reason text suggests '{top_label}' ({top_score:.0%} confidence)"
            )
        extracted["hf_classification"] = top_label
        extracted["hf_confidence"] = round(top_score, 3)

    return extracted


# ── Step 2: Database lookup ───────────────────────────────────────────────────


def query_shipment(po_number: str) -> dict:
    """Look up a PO in the shipments database."""
    init_db()
    result = lookup_shipment(po_number)
    if not result:
        return {"found": False, "po_number": po_number}
    return {"found": True, **result}


# ── Step 3: Edge case detection ───────────────────────────────────────────────


def check_edge_cases(pdf_data: dict, shipment: dict) -> list[str]:
    """
    Rule engine — deterministic checks that gate auto-send.
    Also surfaces HuggingFace classification warnings from Step 1.

    Returns list of flag strings. Empty = safe to auto-draft.
    """
    flags: list[str] = []

    if not shipment.get("found"):
        flags.append(f"PO {pdf_data.get('po_number')} not found in shipment database")
        return flags

    if not shipment.get("bol_number"):
        flags.append("Missing BOL number — cannot prove delivery without it")

    amount = pdf_data.get("deduction_amount", 0)
    if amount > HUMAN_REVIEW_THRESHOLD:
        flags.append(
            f"Dispute amount ${amount:,.2f} exceeds "
            f"${HUMAN_REVIEW_THRESHOLD} auto-approve limit"
        )

    code = pdf_data.get("deduction_code", "")
    if code not in KNOWN_CODES:
        flags.append(f"Unknown deduction code '{code}' — not in codebook")

    # Surface HuggingFace classification mismatch from Step 1
    if "classification_warning" in pdf_data:
        flags.append(f"Classification mismatch: {pdf_data['classification_warning']}")

    return flags


# ── Step 4: Email drafting via HuggingFace Inference API ─────────────────────


def draft_dispute_email(pdf_data: dict, shipment: dict) -> str:
    """
    Draft a dispute email using HuggingFace Inference API.
    Uses Mistral-7B-Instruct — strong instruction-following, free tier,
    no GPU needed (runs on HF servers).
    """
    code = pdf_data.get("deduction_code", "")
    code_desc = KNOWN_CODES.get(code, code)

    prompt = f"""You are a chargeback dispute specialist for a wholesale distributor.
Write a professional dispute email to a retailer's deductions team.
 
Deduction: {code} — {code_desc}
Amount disputed: ${pdf_data.get('deduction_amount'):,.2f}
PO Number: {pdf_data.get('po_number')}
Retailer's reason: "{pdf_data.get('reason_text')}"
 
Our shipment records confirm:
  Ordered:   {shipment['ordered_qty']} units
  Delivered: {shipment['delivered_qty']} units (full order fulfilled)
  Date:      {shipment['delivery_date']}
  Carrier:   {shipment['carrier']}
  BOL:       {shipment['bol_number']}
 
Write a concise, firm dispute letter (3-4 paragraphs).
Cite the BOL number and delivery evidence.
Request full reversal of the deduction.
Sign off as "Accounts Receivable Team".
Do not include a subject line. Start directly with "Dear"."""

    if HF_TOKEN:
        try:
            client = InferenceClient(
                model="Qwen/Qwen2.5-7B-Instruct",
                token=HF_TOKEN,
            )
            response = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"  HF Inference API error: {e}. Falling back to template.")

    # ── Fallback: structured template (no model needed) ───────────────────
    return _template_email(pdf_data, shipment, code_desc)


def _template_email(pdf_data: dict, shipment: dict, code_desc: str) -> str:
    """
    Deterministic fallback email when no LLM is available.
    Good enough for a demo; shows the agent can degrade gracefully.
    """
    return f"""Dear Deductions Team,
 
We are writing to formally dispute deduction code {pdf_data['deduction_code']} \
({code_desc}) of ${pdf_data['deduction_amount']:,.2f} applied against \
purchase order {pdf_data['po_number']}.
 
Our shipment records confirm that {shipment['ordered_qty']} units were ordered \
and {shipment['delivered_qty']} units were delivered in full on \
{shipment['delivery_date']} via {shipment['carrier']}. \
Proof of delivery is documented under Bill of Lading {shipment['bol_number']}, \
which we have attached for your reference.
 
Given the evidence above, we respectfully request the full reversal of this \
deduction. Please confirm receipt of this dispute and advise on your expected \
processing timeline.
 
Accounts Receivable Team"""
