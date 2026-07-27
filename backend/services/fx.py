"""Live currency conversion rates, for reconciling a foreign-currency
student's balance against an INR bank credit. Sourced from Frankfurter
(European Central Bank reference rates) — free, no API key, no rate limits.

This is a reference rate, not her bank's actual conversion rate (which will
include a margin/fee) — the frontend always shows it as an editable
starting point, never a final figure.
"""

import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"

_cache = {}  # (from, to) -> (rate, fetched_at_epoch)
_CACHE_TTL_SECONDS = 3600  # rates don't move meaningfully within an hour


async def get_rate(from_currency: str, to_currency: str) -> Optional[float]:
    if from_currency == to_currency:
        return 1.0

    key = (from_currency, to_currency)
    cached = _cache.get(key)
    if cached and time.time() - cached[1] < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(FRANKFURTER_URL, params={"base": from_currency, "symbols": to_currency})
        resp.raise_for_status()
        rate = resp.json()["rates"][to_currency]
        _cache[key] = (rate, time.time())
        return rate
    except Exception as e:
        logger.error(f"FX rate fetch failed for {from_currency}->{to_currency}: {e}")
        return cached[0] if cached else None  # stale cache beats no rate at all
