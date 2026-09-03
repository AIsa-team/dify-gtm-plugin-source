"""Shared AIsa API client for the Go-to-Market Dify plugin.

All tools in this plugin talk to the AIsa unified API
(https://api.aisa.one) with a single API key. The key comes from the
Dify provider credential ``aisa_api_key`` — never from environment
variables or local files, since this code runs inside Dify's plugin
sandbox.

Error-handling contract (important):
    The AIsa API is known to return error payloads inside HTTP 200
    responses. Callers must NEVER trust the status code alone — this
    client inspects every response body for an ``error`` field /
    ``success: false`` marker and raises a typed exception instead of
    returning a poisoned payload.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

GTM_PLAN_URL = "https://aisa.one/solutions/go-to-market"

AUTH_HINT = (
    "Invalid or missing AIsa API key. Get one with the AIsa Go-to-Market plan "
    f"($39/mo, includes $50 API credit): {GTM_PLAN_URL}"
)
CREDIT_HINT = (
    "AIsa API credit exhausted. Top up your balance or subscribe to the "
    f"AIsa Go-to-Market plan ($39/mo, includes $50 API credit): {GTM_PLAN_URL}"
)

_AUTH_MARKERS = ("401", "403", "UNAUTHORIZED", "FORBIDDEN", "INVALID_API_KEY", "INVALID_KEY")
_CREDIT_MARKERS = (
    "402",
    "PAYMENT",
    "INSUFFICIENT",
    "QUOTA",
    "CREDIT",
    "BALANCE",
    "LIMIT_EXCEEDED",
)


class AisaApiError(Exception):
    """Base error for AIsa API failures."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class AisaAuthError(AisaApiError):
    """API key missing, invalid, or revoked."""


class AisaCreditError(AisaApiError):
    """Plan credit or quota exhausted."""


def _classify_and_raise(code: str, message: str) -> None:
    """Map an API error to the right typed exception, with an actionable hint."""
    haystack = f"{code} {message}".upper()
    if any(marker in haystack for marker in _AUTH_MARKERS):
        raise AisaAuthError(code, f"{message}. {AUTH_HINT}")
    if any(marker in haystack for marker in _CREDIT_MARKERS):
        raise AisaCreditError(code, f"{message}. {CREDIT_HINT}")
    raise AisaApiError(code, message)


# Required query params per endpoint (from AIsa's audited tool contracts).
# Used for the contract-drift fallback: when the gateway rejects a request as
# "does not match the endpoint contract", retry once with required params only
# — this self-heals the drift class where a documented optional param stops
# being accepted (as happened to semrush keyword-overview's 'database').
# Endpoints whose optionals carry the query semantics (Apollo searches) are
# deliberately ABSENT: dropping their filters would return billed garbage.
_REQUIRED_PARAMS = {
    "/semrush/keyword-overview": {"phrase"},
    "/semrush/keyword-difficulty": {"phrase"},
    "/semrush/domain-organic-keywords": {"domain", "database"},
    "/semrush/domain-organic-competitors": {"domain", "database"},
    "/semrush/backlinks-overview": {"target"},
    "/similarweb/website-traffic-snapshot": {"domain"},
    "/similarweb/website-traffic-trend": {"domain"},
    "/similarweb/website/traffic-engagement": {"domain", "start_date", "end_date", "metrics"},
    "/similarweb/website/ranking": {"domain", "start_date", "end_date"},
    "/similarweb/website-top-geographies": {"domain"},
    "/similarweb/website/demographics": {"domain", "start_date", "end_date", "granularity"},
    "/similarweb/website/similar-sites": {"domain", "start_date", "end_date", "limit"},
    "/similarweb/website/technologies": {"domain", "start_date", "end_date", "granularity", "limit"},
    "/similarweb/website/popular-pages": {"domain", "start_date", "end_date", "limit"},
    "/ahrefs/site-explorer/domain-rating": {"target", "date"},
    "/ahrefs/site-explorer/metrics": {"target", "date"},
    "/twitter/tweet/advanced_search": {"query", "queryType"},
    "/twitter/user/info": {"userName"},
    "/reddit/search": {"query"},
    "/reddit/subreddit/search": {"subreddit"},
    "/instagram/reels/search": {"query"},
    "/instagram/profile": {"handle"},
    "/pinterest/search": {"query"},
    "/youtube/search": {"engine", "q"},
    "/apollo/organizations/enrich": {"domain"},
}

_CONTRACT_MISMATCH_MARKER = "does not match the endpoint contract"


class AisaClient:
    """Minimal AIsa API client (stdlib only — no extra dependencies)."""

    BASE_URL = "https://api.aisa.one/apis/v1"
    # Account endpoints (/credits/balance, /usage) live on the /v1 server,
    # not /apis/v1 — per-operation server override in AIsa's OpenAPI spec.
    ACCOUNT_BASE_URL = "https://api.aisa.one/v1"

    def __init__(self, api_key: str):
        api_key = (api_key or "").strip()
        if not api_key:
            raise AisaAuthError("MISSING_KEY", AUTH_HINT)
        self.api_key = api_key

    # ------------------------------------------------------------------ core

    def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 100,
        retries: int = 1,
        retry_delay_seconds: int = 3,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make a request; on a gateway contract-mismatch, self-heal once.

        If the gateway rejects the request shape and the endpoint has a known
        required-params set, retry with required params only and annotate the
        result with '_contract_fallback' so callers can disclose the drift."""
        try:
            return self._request_once(
                method, endpoint, params, data, timeout, retries,
                retry_delay_seconds, base_url,
            )
        except AisaApiError as e:
            minimal = self._minimal_params(endpoint, params)
            if minimal is None or _CONTRACT_MISMATCH_MARKER not in e.message:
                raise
            result = self._request_once(
                method, endpoint, minimal, data, timeout, retries,
                retry_delay_seconds, base_url,
            )
            if isinstance(result, dict):
                dropped = sorted(set(params or {}) - set(minimal))
                result["_contract_fallback"] = {
                    "dropped_params": dropped,
                    "note": "Endpoint contract drifted upstream; retried with "
                            "required parameters only.",
                }
            return result

    @staticmethod
    def _minimal_params(
        endpoint: str, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Required-only param subset, or None when fallback doesn't apply."""
        required = _REQUIRED_PARAMS.get(endpoint)
        if not required or not params:
            return None
        minimal = {k: v for k, v in params.items() if k in required}
        sent = {k for k, v in params.items() if v is not None}
        if sent == set(minimal):
            return None  # nothing to drop — retry would be identical
        return minimal

    def _request_once(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 100,
        retries: int = 1,
        retry_delay_seconds: int = 3,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make a request and return the parsed, error-checked JSON body."""
        url = f"{base_url or self.BASE_URL}{endpoint}"
        if params:
            # doseq=True so list values expand to repeated keys (Apollo-style
            # array params, e.g. person_titles[]). quote_via=quote encodes
            # spaces as %20 (RFC 3986) rather than '+' — the gateway's
            # contract validator rejects '+'-encoded spaces in query values.
            query_string = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None},
                doseq=True,
                quote_via=urllib.parse.quote,
            )
            url = f"{url}?{query_string}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "AIsa-GTM-Dify-Plugin/0.1",
        }

        request_data = None
        if data is not None:
            request_data = json.dumps(data).encode("utf-8")
        if method == "POST" and request_data is None:
            request_data = b"{}"
        # Declare a JSON body only when we actually send one. A bodyless GET
        # carrying "Content-Type: application/json" contradicts contracts that
        # define no request body, and the gateway's per-module validator can
        # reject that as "request does not match the endpoint contract".
        if request_data is not None:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=request_data, headers=headers, method=method)

        attempts = retries + 1
        last_error: Optional[AisaApiError] = None
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                    content_type = (response.headers.get("Content-Type") or "").lower()
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    # Some providers (Semrush) answer with semicolon-delimited
                    # text/plain per their contract — return it structured
                    # instead of failing on the JSON assumption.
                    if "json" in content_type:
                        raise
                    return _parse_delimited_text(raw)
                return self._check_body(body)
            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8", errors="replace")
                if e.code in {502, 503, 504} and attempt < attempts:
                    time.sleep(retry_delay_seconds)
                    continue
                try:
                    parsed = json.loads(error_body)
                    code, message = self._extract_error(parsed, default_code=str(e.code))
                except (json.JSONDecodeError, ValueError):
                    code, message = str(e.code), error_body[:500] or e.reason
                _classify_and_raise(code, message)
            except urllib.error.URLError as e:
                if attempt < attempts:
                    time.sleep(retry_delay_seconds)
                    continue
                last_error = AisaApiError("NETWORK_ERROR", str(e.reason))
            except json.JSONDecodeError:
                last_error = AisaApiError(
                    "BAD_RESPONSE", "AIsa API returned a non-JSON response."
                )
                break

        raise last_error or AisaApiError("UNKNOWN_ERROR", "Request failed unexpectedly.")

    def _check_body(self, body: Any) -> Dict[str, Any]:
        """Reject error payloads hiding inside HTTP 200 responses."""
        if not isinstance(body, dict):
            return {"data": body}
        if body.get("error") or body.get("success") is False:
            code, message = self._extract_error(body, default_code="API_ERROR")
            _classify_and_raise(code, message)
        return body

    @staticmethod
    def _extract_error(body: Dict[str, Any], default_code: str) -> tuple:
        error = body.get("error")
        if isinstance(error, dict):
            return (
                str(error.get("code", default_code)),
                str(error.get("message", "Unknown AIsa API error")),
            )
        if isinstance(error, str) and error:
            return default_code, error
        return default_code, str(body.get("message", "Unknown AIsa API error"))

    # --------------------------------------------------------------- account

    def credits_balance(self) -> Dict[str, Any]:
        """Account balance — free call, used for credential validation."""
        return self.request(
            "GET", "/credits/balance", timeout=30, base_url=self.ACCOUNT_BASE_URL
        )

    # ---------------------------------------------------------------- tavily

    def tavily_search(self, query: str) -> Dict[str, Any]:
        return self.request("POST", "/tavily/search", data={"query": query})

    def tavily_extract(self, urls: List[str]) -> Dict[str, Any]:
        return self.request("POST", "/tavily/extract", data={"urls": urls})

    def tavily_crawl(self, url: str, max_depth: int = 2) -> Dict[str, Any]:
        return self.request(
            "POST", "/tavily/crawl", data={"url": url, "max_depth": max_depth}
        )

    def tavily_map(self, url: str) -> Dict[str, Any]:
        return self.request("POST", "/tavily/map", data={"url": url})


def _parse_delimited_text(raw: str) -> Dict[str, Any]:
    """Parse a semicolon-delimited text/plain response (Semrush style).

    Semrush analytics responses are CSV-style rows separated by ';', usually
    with a header row (e.g. "Keyword;Search Volume;CPC;..."). Returns both the
    raw text and best-effort structured rows so downstream code and agents can
    use whichever they need.
    """
    text = raw.strip()
    lines = [line for line in text.splitlines() if line.strip()]
    rows: List[Dict[str, Any]] = []
    if lines and ";" in lines[0]:
        first = [c.strip() for c in lines[0].split(";")]
        # Header row heuristic: no cell in the first row is purely numeric.
        def _is_numericish(cell: str) -> bool:
            return bool(cell) and cell.replace(".", "", 1).replace("-", "", 1).isdigit()

        has_header = len(lines) > 1 and not any(_is_numericish(c) for c in first)
        if has_header:
            for line in lines[1:]:
                cells = [c.strip() for c in line.split(";")]
                rows.append(dict(zip(first, cells)))
        else:
            for line in lines:
                cells = [c.strip() for c in line.split(";")]
                rows.append({f"col_{i}": c for i, c in enumerate(cells)})
    return {"format": "delimited_text", "raw_text": text[:20000], "results": rows}


def find_results(payload: Any) -> List[Dict[str, Any]]:
    """Locate the main record list in a response without assuming an exact shape.

    AIsa proxies many upstream providers, each with its own envelope. This
    walks the usual wrapper keys and returns the first list of dicts found.
    """
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("results", "data", "tasks", "items", "records", "pages", "urls",
                    "people", "organizations", "accounts", "contacts", "creators",
                    "tweets", "posts", "profiles", "result"):
            if key in payload:
                found = find_results(payload[key])
                if found:
                    return found
    return []


_SUMMARY_ID_KEYS = (
    "name", "title", "question", "domain", "url", "keyword", "phrase",
    "handle", "userName", "username", "full_name", "organization_name",
    "subreddit", "text", "id",
)


def generic_summary(title: str, result: Any, max_items: int = 8) -> str:
    """Compact, agent-friendly text view of an arbitrary JSON result."""
    items = find_results(result)
    lines = [title]
    if items:
        shown = items[:max_items]
        lines.append(f"{len(items)} record(s) returned. First {len(shown)}:")
        for item in shown:
            lowered = {k.lower(): k for k in item}
            keys = [lowered[k] for k in _SUMMARY_ID_KEYS if k.lower() in lowered and item[lowered[k.lower()]]]
            if keys:
                lines.append(
                    "- " + ", ".join(f"{k}={str(item[k])[:70]}" for k in keys[:3])
                )
            else:
                lines.append("- " + json.dumps(item, ensure_ascii=False)[:140])
        if len(items) > max_items:
            lines.append(f"(+{len(items) - max_items} more in the JSON payload)")
    else:
        lines.append("Structured payload returned — see the JSON output for details.")
    return "\n".join(lines)


def truncate_payload(value: Any, max_field_chars: int = 8000) -> Any:
    """Recursively cap long text fields so tool output stays context-friendly.

    Adds an explicit truncation marker so downstream agents know content
    was cut rather than silently missing.
    """
    if isinstance(value, str):
        if len(value) > max_field_chars:
            return value[:max_field_chars] + f"... [truncated, {len(value)} chars total]"
        return value
    if isinstance(value, list):
        return [truncate_payload(item, max_field_chars) for item in value]
    if isinstance(value, dict):
        return {k: truncate_payload(v, max_field_chars) for k, v in value.items()}
    return value
