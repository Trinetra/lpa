"""Best-effort venue geocoding for tour stops, via Nominatim (OpenStreetMap) —
free, no API key, worldwide coverage, appropriate for the low request volume
of a solo touring dance studio. Never raises: a stop should always save even
if the venue name doesn't geocode cleanly (ambiguous name, typo, Nominatim
hiccup) — she can retry by editing the stop once the venue text is fixed.

Nominatim's usage policy asks for a descriptive User-Agent and at most
~1 request/second — both are trivially satisfied here.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "LakshmiStudioLedger/1.0 (tour venue geocoding)"


async def geocode_venue(venue: Optional[str], city: str) -> Optional[dict]:
    query = ", ".join(p for p in [venue, city] if p)
    if not query:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(
                NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
                headers={"User-Agent": USER_AGENT},
            )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        r = results[0]
        return {
            "latitude": float(r["lat"]),
            "longitude": float(r["lon"]),
            "formatted_address": r.get("display_name"),
        }
    except Exception as e:
        logger.warning(f"Geocoding failed for '{query}': {e}")
        return None
