"""Tour expense export helpers (CSV + PDF). Pure functions — no database access."""

import csv
import io
from collections import defaultdict
from typing import Optional


def expenses_to_csv(tour: dict, expenses: list) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Category", "Currency", "Amount", "Notes"])
    totals_by_currency = defaultdict(float)
    for e in expenses:
        amount = float(e.get("amount", 0))
        currency = e.get("currency", "INR")
        totals_by_currency[currency] += amount
        writer.writerow([
            e.get("expense_date", ""),
            e.get("category", ""),
            currency,
            f"{amount:.2f}",
            e.get("notes") or "",
        ])
    writer.writerow([])
    # One total row per currency actually used — expenses on a tour commonly
    # span more than one (flights in USD, local transport in GBP, etc.), so a
    # single blended sum across currencies would be meaningless.
    for currency, total in sorted(totals_by_currency.items()):
        writer.writerow(["", f"Total ({currency})", currency, f"{total:.2f}", ""])
    return buf.getvalue().encode("utf-8")
