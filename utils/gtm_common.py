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


# --- Human-in-the-loop price gate -----------------------------------------
# Per-call prices from AIsa's live pricing overlay (audited 2026-09).
CALL_PRICES = {
    ("keyword_seo", "keyword_overview"): 0.003,
    ("keyword_seo", "keyword_suggestions"): 0.012,
    ("keyword_seo", "search_volume"): 0.012,
    ("keyword_seo", "domain_keywords"): 0.09,
    ("keyword_seo", "backlinks_overview"): 0.01,
    ("keyword_seo", "keyword_difficulty"): 0.45,
    ("keyword_seo", "domain_competitors"): 0.36,
    ("traffic_intel", "overview"): 0.0,
    ("traffic_intel", "trend"): 0.0,
    ("traffic_intel", "engagement"): 0.10,
    ("traffic_intel", "ranking"): 0.10,
    ("traffic_intel", "geographies"): 0.10,
    ("traffic_intel", "demographics"): 0.10,
    ("traffic_intel", "similar_sites"): 0.10,
    ("traffic_intel", "technologies"): 0.10,
    ("traffic_intel", "popular_pages"): 0.10,
    ("traffic_intel", "domain_authority"): 0.26,
}

DEFAULT_APPROVAL_THRESHOLD = 0.30


def parse_threshold(raw) -> float:
    """User-supplied approval threshold, defaulting safely."""
    try:
        value = float(raw)
        return value if value >= 0 else DEFAULT_APPROVAL_THRESHOLD
    except (TypeError, ValueError):
        return DEFAULT_APPROVAL_THRESHOLD


def approval_notice(tool: str, metric: str, tool_parameters: dict):
    """Return a requires_approval notice dict when this call must be approved
    first, else None. Gates calls costing AT LEAST the threshold. Free —
    evaluated before any API call."""
    if tool_parameters.get("approved"):
        return None
    price = CALL_PRICES.get((tool, metric), 0.0)
    threshold = parse_threshold(tool_parameters.get("approval_threshold"))
    if price < threshold or price <= 0:
        return None
    return {
        "requires_approval": True,
        "metric": metric,
        "estimated_cost": f"${price:.2f}",
        "approval_threshold": f"${threshold:.2f}",
        "message": (
            f"'{metric}' costs ${price:.2f}, at or above the approval threshold "
            f"(${threshold:.2f}). No data was fetched and nothing was charged. "
            "Get the user's approval, then retry this exact call with "
            "approved=true. Never set approved=true without the user's consent."
        ),
    }
