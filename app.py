import os
import re
import sys

import fitz
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

from chargeback_bot.tools import check_edge_cases, draft_dispute_email, query_shipment
from flag_human.db import init_db

init_db()

KNOWN_CODES = {
    "SS": "Short shipment",
    "LD": "Late delivery",
    "LB": "Labeling violation",
    "PD": "Price discrepancy",
    "DA": "Damaged goods",
}


def parse_pdf(pdf_bytes: bytes) -> dict:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    raw_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    po_match = re.search(r"PO\s*(?:Number|#)?\s*:?\s*(PO-\w+)", raw_text, re.I)
    code_match = re.search(r"Deduction\s*Code\s*:?\s*([A-Z]{2,6}(?:-\d+)?)", raw_text, re.I)
    amount_match = re.search(r"Deduction\s*Amount\s*:?\s*\$?([\d,]+\.?\d*)", raw_text, re.I)
    reason_match = re.search(r"Reason\s*:?\s*(.+)", raw_text, re.I)

    return {
        "po_number": po_match.group(1).strip() if po_match else "UNKNOWN",
        "deduction_code": code_match.group(1).strip().upper() if code_match else "UNKNOWN",
        "deduction_amount": float(amount_match.group(1).replace(",", "")) if amount_match else 0.0,
        "reason_text": reason_match.group(1).strip() if reason_match else "",
    }


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Chargeback Dispute Bot",
    page_icon="📄",
    layout="centered",
)

st.title("📄 Chargeback Dispute Bot")
st.caption(
    "Upload a remittance advice PDF to auto-draft a dispute letter "
    "or route it for human review."
)

with st.expander("How it works"):
    st.markdown(
        """
        1. **Parse** — extracts PO number, deduction code, and amount from the PDF
        2. **Look up** — matches the PO against shipment records in SQLite
        3. **Check** — rule engine flags missing BOL, unknown code, or amount > $500
        4. **Draft** — generates a dispute email via HuggingFace Inference API
        """
    )

with st.expander("Test POs seeded in the demo database"):
    st.markdown(
        """
        | PO | Code | Amount | BOL | Expected outcome |
        |----|------|--------|-----|-----------------|
        | PO-8821 | SS | $240 | BOL-4492 | Auto-drafted ✅ |
        | PO-9034 | LD | $180 | *(missing)* | Human review ⚠️ |

        Generate a test PDF with `python tests/evals/generate_sample.py`.
        """
    )

st.divider()

uploaded = st.file_uploader("Upload remittance PDF", type=["pdf"])

if uploaded:
    pdf_bytes = uploaded.read()

    with st.status("Running pipeline…", expanded=True) as pipeline_status:

        st.write("**1 / 3** — Parsing PDF…")
        pdf_data = parse_pdf(pdf_bytes)
        col1, col2, col3 = st.columns(3)
        col1.metric("PO", pdf_data["po_number"])
        col2.metric("Code", f"{pdf_data['deduction_code']} · {KNOWN_CODES.get(pdf_data['deduction_code'], 'Unknown')}")
        col3.metric("Amount", f"${pdf_data['deduction_amount']:,.2f}")

        st.write("**2 / 3** — Looking up shipment record…")
        shipment = query_shipment(pdf_data["po_number"])
        if shipment["found"]:
            bol = shipment.get("bol_number") or "MISSING"
            st.write(
                f"Found — {shipment['delivered_qty']}/{shipment['ordered_qty']} units "
                f"delivered on {shipment['delivery_date']} via {shipment['carrier']} · BOL: `{bol}`"
            )
        else:
            st.write(f"PO `{pdf_data['po_number']}` not found in database")

        st.write("**3 / 3** — Checking edge cases…")
        flags = check_edge_cases(pdf_data, shipment)

        if flags:
            pipeline_status.update(
                label="Flagged for human review", state="error", expanded=True
            )
        else:
            email = draft_dispute_email(pdf_data, shipment)
            pipeline_status.update(
                label="Pipeline complete — ready to send", state="complete", expanded=False
            )

    st.divider()

    if flags:
        st.error("**Flagged for human review**")
        for flag in flags:
            st.warning(flag)
    else:
        st.success("**Draft ready**")
        st.text_area(
            "Dispute email",
            email,
            height=340,
            label_visibility="collapsed",
        )
        st.download_button(
            "⬇ Download as .txt",
            data=email,
            file_name=f"dispute_{pdf_data['po_number']}.txt",
            mime="text/plain",
        )
