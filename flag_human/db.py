import sqlite3


def init_db():
    conn = sqlite3.connect("chargebacks.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            po_number TEXT PRIMARY KEY,
            ordered_qty INTEGER,
            delivered_qty INTEGER,
            delivery_date TEXT,
            carrier TEXT,
            bol_number TEXT
        )
    """)
    # Seed with test data
    conn.execute(
        "INSERT OR IGNORE INTO shipments VALUES (?,?,?,?,?,?)",
        ("PO-8821", 144, 144, "2025-05-12", "FedEx Freight", "BOL-4492"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO shipments VALUES (?,?,?,?,?,?)",
        ("PO-9034", 96, 96, "2025-05-19", "Old Dominion", None),
    )  # missing BOL
    conn.commit()
    return conn


def lookup_shipment(po_number: str) -> dict | None:
    conn = sqlite3.connect("chargebacks.db")
    row = conn.execute(
        "SELECT * FROM shipments WHERE po_number = ?", (po_number,)
    ).fetchone()
    if not row:
        return None
    return dict(
        zip(
            [
                "po_number",
                "ordered_qty",
                "delivered_qty",
                "delivery_date",
                "carrier",
                "bol_number",
            ],
            row,
        )
    )
