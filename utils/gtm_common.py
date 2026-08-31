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
