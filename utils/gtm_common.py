"""Shared helpers for the GTM tools: date-range defaults and geo mapping."""

from datetime import date
from typing import Optional, Tuple

# Similarweb data is published with roughly a two-month lag; monthly endpoints
# reject months that are too recent. Default window: a 3-month range ending
# two months before the current month.
_SIMILARWEB_LAG_MONTHS = 2


def _shift_month(year: int, month: int, delta: int) -> Tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_str(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def default_month_range(
    span_months: int = 2, lag_months: int = _SIMILARWEB_LAG_MONTHS
) -> Tuple[str, str]:
    """(start, end) months in YYYY-MM, `span_months` apart, lagged from today."""
    today = date.today()
    end_y, end_m = _shift_month(today.year, today.month, -lag_months)
    start_y, start_m = _shift_month(end_y, end_m, -span_months)
    return month_str(start_y, start_m), month_str(end_y, end_m)


def today_str() -> str:
    return date.today().isoformat()


def shift_month_str(year_month: str, delta: int) -> str:
    """Shift a 'YYYY-MM' string by delta months."""
    year, month = int(year_month[:4]), int(year_month[5:7])
    y, m = _shift_month(year, month, delta)
    return month_str(y, m)


# Country code -> DataForSEO location_name, for the major GTM markets.
# Unknown codes fall back to no location filter (worldwide/US default upstream).
_DFS_LOCATIONS = {
    "us": "United States",
    "uk": "United Kingdom",
    "gb": "United Kingdom",
    "ca": "Canada",
    "au": "Australia",
    "de": "Germany",
    "fr": "France",
    "es": "Spain",
    "it": "Italy",
    "nl": "Netherlands",
    "jp": "Japan",
    "kr": "South Korea",
    "br": "Brazil",
    "mx": "Mexico",
    "in": "India",
    "sg": "Singapore",
    "hk": "Hong Kong",
    "pl": "Poland",
    "se": "Sweden",
    "ie": "Ireland",
    "pt": "Portugal",
    "be": "Belgium",
    "at": "Austria",
    "dk": "Denmark",
    "fi": "Finland",
    "no": "Norway",
    "cz": "Czech Republic",
    "gr": "Greece",
    "ro": "Romania",
    "hu": "Hungary",
    "ch": "Switzerland",
}


# LLM agents often pass full country names instead of codes — normalize.
_COUNTRY_NAMES = {
    "united states": "us", "usa": "us", "america": "us",
    "united kingdom": "uk", "great britain": "uk", "britain": "uk", "england": "uk",
    "canada": "ca", "australia": "au", "germany": "de", "france": "fr",
    "spain": "es", "italy": "it", "netherlands": "nl", "japan": "jp",
    "south korea": "kr", "korea": "kr", "brazil": "br", "mexico": "mx",
    "india": "in", "singapore": "sg", "hong kong": "hk",
    "poland": "pl", "sweden": "se", "ireland": "ie", "portugal": "pt",
    "belgium": "be", "austria": "at", "denmark": "dk", "finland": "fi",
    "norway": "no", "czech republic": "cz", "czechia": "cz", "greece": "gr",
    "romania": "ro", "hungary": "hu", "switzerland": "ch",
}


def normalize_country(country: str) -> str:
    """Best-effort 2-letter code from whatever the agent passed. Fallback: us."""
    raw = (country or "").strip().lower()
    if not raw:
        return "us"
    if raw in _COUNTRY_NAMES:
        return _COUNTRY_NAMES[raw]
    if len(raw) == 2 and raw.isalpha():
        return "uk" if raw == "gb" else raw
    return "us"


def dfs_location_name(country: str) -> Optional[str]:
    return _DFS_LOCATIONS.get(normalize_country(country))


def semrush_database(country: str) -> str:
    """Semrush regional database code — 2-letter, 'uk' for Britain."""
    return normalize_country(country)


# --- Human-in-the-loop price gate (quote-first) ----------------------------
# Every data-plane request is price-quoted upstream FIRST — free, via the
# gateway's 'X-AISA-Cost-Mode: quote' header — and the LIVE quote drives the
# approval gate (AisaClient._enforce_cost_guard). There is deliberately NO
# static price table anywhere in this plugin: upstream prices move (observed
# 2026-09: traffic snapshot $0 -> $0.52, Semrush difficulty $0.45 -> ~$0.01
# per keyword), so a maintained table is a liability, not a safety net.
# When the quote plane itself is unavailable the gate FAILS SAFE: the call
# is refused as unpriceable until the user explicitly approves it.

DEFAULT_APPROVAL_THRESHOLD = 0.30


def parse_threshold(raw) -> float:
    """User-supplied approval threshold, defaulting safely."""
    try:
        value = float(raw)
        return value if value >= 0 else DEFAULT_APPROVAL_THRESHOLD
    except (TypeError, ValueError):
        return DEFAULT_APPROVAL_THRESHOLD


class CostGuard:
    """Per-invocation price gate, consulted by AisaClient before EVERY call.

    The client quotes each request upstream (free) and asks this guard to
    decide; the guard returns a structured approval notice when the price is
    at or above the user's threshold and the call wasn't pre-approved."""

    def __init__(self, tool: str, metric: str, threshold: float, approved: bool):
        self.tool = tool
        self.metric = metric
        self.threshold = threshold
        self.approved = approved

    @classmethod
    def from_params(cls, tool: str, metric: str, tool_parameters: dict) -> "CostGuard":
        return cls(
            tool,
            metric,
            parse_threshold(tool_parameters.get("approval_threshold")),
            bool(tool_parameters.get("approved")),
        )

    def decide(self, price_usd, endpoint: str, source: str):
        """Approval notice dict when the call must be approved first, else None.

        price_usd is None when the quote plane could not price the call —
        that FAILS SAFE: unpriceable calls need explicit approval."""
        if self.approved:
            return None
        if price_usd is None:
            return {
                "requires_approval": True,
                "metric": self.metric,
                "endpoint": endpoint,
                "estimated_cost": "unknown",
                "price_source": "quote_unavailable",
                "approval_threshold": f"${self.threshold:.2f}",
                "message": (
                    f"'{self.metric}' could not be priced — the upstream quote "
                    "service did not answer, and this plugin keeps no static "
                    "price list. No data was fetched and nothing was charged. "
                    "To run it anyway at unquoted cost, get the user's explicit "
                    "approval, then retry this exact call with approved=true. "
                    "Never set approved=true without the user's consent."
                ),
            }
        if price_usd <= 0 or price_usd < self.threshold:
            return None
        return {
            "requires_approval": True,
            "metric": self.metric,
            "endpoint": endpoint,
            "estimated_cost": f"${price_usd:.2f}",
            "price_source": source,
            "approval_threshold": f"${self.threshold:.2f}",
            "message": (
                f"'{self.metric}' is priced at ${price_usd:.2f} (live upstream "
                f"quote), at or above the approval threshold "
                f"(${self.threshold:.2f}). No data was fetched and nothing was "
                "charged. Get the user's approval, then retry this exact call "
                "with approved=true. Never set approved=true without the "
                "user's consent."
            ),
        }
