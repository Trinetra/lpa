"""Tour expense export helpers (CSV + PDF). Pure functions — no database access."""

import csv
import io
from typing import Optional


def expenses_to_csv(tour: dict, expenses: list) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Category", "Amount (INR)", "Notes"])
    total = 0.0
    for e in expenses:
        amount = float(e.get("amount", 0))
        total += amount
        writer.writerow([
            e.get("expense_date", ""),
            e.get("category", ""),
            f"{amount:.2f}",
            e.get("notes") or "",
        ])
    writer.writerow([])
    writer.writerow(["", "Total", f"{total:.2f}", ""])
    return buf.getvalue().encode("utf-8")
