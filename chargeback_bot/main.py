from chargeback_bot.tools import (
    parse_pdf,
    query_shipment,
    check_edge_cases,
    draft_dispute_email,
)
from flag_human.db import init_db


def run_pipeline(input_data):
    print("=" * 50)

    # Accept a pre-parsed dict to bypass PDF parsing (used in tests)
    if isinstance(input_data, dict):
        pdf_data = {
            "po_number": input_data.get("po", input_data.get("po_number", "UNKNOWN")),
            "deduction_code": input_data.get("code", input_data.get("deduction_code", "UNKNOWN")),
            "deduction_amount": float(input_data.get("amount", input_data.get("deduction_amount", 0))),
            "reason_text": input_data.get("reason_text", ""),
        }
        print(f"Processing dict input: PO={pdf_data['po_number']}, Code={pdf_data['deduction_code']}, Amount=${pdf_data['deduction_amount']}")
        print("=" * 50)
    else:
        pdf_path = input_data
        print(f"Processing: {pdf_path}")
        print("=" * 50)

        # Step 1: Parse PDF
        print("\n[1/4] Parsing PDF...")
        pdf_data = parse_pdf(pdf_path)
    print(
        f"  → PO: {pdf_data['po_number']}, Code: {pdf_data['deduction_code']}, Amount: ${pdf_data['deduction_amount']}"
    )

    # Step 2: Query database
    print("\n[2/4] Looking up shipment record...")
    shipment = query_shipment(pdf_data["po_number"])
    if shipment["found"]:
        print(
            f"  → Found: {shipment['delivered_qty']}/{shipment['ordered_qty']} units, BOL: {shipment.get('bol_number', 'MISSING')}"
        )
    else:
        print("  → NOT FOUND in database")

    # Step 3: Check edge cases (the "brain" of the agent)
    print("\n[3/4] Checking edge cases...")
    flags = check_edge_cases(pdf_data, shipment)

    if flags:
        print("  → FLAGGING FOR HUMAN REVIEW:")
        for f in flags:
            print(f"     ⚠ {f}")
        # In production: write to a review queue, send Slack alert, etc.
        return {"status": "human_review", "flags": flags, "data": pdf_data}

    # Step 4: Draft and send email
    print("\n[4/4] Drafting dispute email...")
    email = draft_dispute_email(pdf_data, shipment)
    print(f"\n--- DRAFT EMAIL ---\n{email}\n---")
    # In production: send via Gmail API or SMTP

    return {"status": "auto_drafted", "email": email}


if __name__ == "__main__":
    init_db()
    result = run_pipeline("sample.pdf")
    print(f"\nFinal status: {result['status']}")
