from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import (
    AisaApiError, AisaApprovalRequired, AisaClient, generic_summary, truncate_payload,
)
from utils.gtm_common import CostGuard, default_month_range, shift_month_str, today_str


def _latest_published_month(snapshot: Any) -> str:
    """Extract the latest published month from a traffic-snapshot response.

    The snapshot endpoint auto-selects the most recent available month,
    echoing it in meta.end_date / data.month ('YYYY-MM')."""
    if isinstance(snapshot, dict):
        meta = snapshot.get("meta") or {}
        data = snapshot.get("data") or {}
        for value in (meta.get("end_date"), data.get("month")):
            if isinstance(value, str) and len(value) >= 7:
                return value[:7]
    return ""


def _resolve_window(client, domain, sw_country, tool_parameters, span: int):
    """(start, end) months for a dated Similarweb metric.

    Per-endpoint upstream rules: demographics/technologies accept EXACTLY one
    monthly bucket; similar_sites exactly three anchored to the latest
    published window. User-supplied dates are always respected verbatim.

    The snapshot anchor probe is NO LONGER free upstream (repriced from $0 to
    ~$0.52, verified 2026-09-14), so it only runs on pre-approved calls; the
    default path uses the free lagged window, and _dated_request self-heals a
    stale window by advancing one month."""
    user_s = str(tool_parameters.get("start_date") or "").strip()
    user_e = str(tool_parameters.get("end_date") or "").strip()
    if user_s and user_e:
        return user_s, user_e
    if tool_parameters.get("approved"):
        try:
            probe = client.request(
                "GET", "/similarweb/website-traffic-snapshot",
                params={"domain": domain, "country": sw_country},
            )
            latest = _latest_published_month(probe)
            if latest:
                return shift_month_str(latest, -(span - 1)), latest
        except AisaApiError:
            pass
    _, end = default_month_range()
    return shift_month_str(end, -(span - 1)), end


_WINDOW_ERROR_MARKERS = ("101", "120", "Dates not in range", "span exactly", "SAME month")


def _dated_request(client, path, base_params, start, end, span: int):
    """Issue a dated request; on an upstream window rejection, advance the
    window one month (keeping the span) and retry once."""
    try:
        return client.request(
            "GET", path, params={**base_params, "start_date": start, "end_date": end}
        )
    except AisaApiError as e:
        if not any(m in e.message for m in _WINDOW_ERROR_MARKERS):
            raise
        new_end = shift_month_str(end, 1)
        new_start = shift_month_str(new_end, -(span - 1))
        return client.request(
            "GET", path,
            params={**base_params, "start_date": new_start, "end_date": new_end},
        )

_METRICS = (
    "overview",
    "trend",
    "engagement",
    "ranking",
    "geographies",
    "demographics",
    "similar_sites",
    "technologies",
    "popular_pages",
    "keyword_competitors",
    "landing_pages",
    "domain_authority",
)


class TrafficIntelTool(Tool):
    """Domain traffic, engagement, audience, and authority — Similarweb + Ahrefs."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        domain = str(tool_parameters.get("domain") or "").strip()
        domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
        metric = str(tool_parameters.get("metric") or "overview").strip().lower()
        country = str(tool_parameters.get("country") or "").strip().lower()

        if not domain:
            yield self.create_json_message(
                {"error": {"code": "INVALID_INPUT", "message": "The 'domain' parameter is required."}}
            )
            return
        if metric not in _METRICS:
            yield self.create_json_message(
                {"error": {"code": "INVALID_INPUT",
                           "message": f"Unknown metric '{metric}'. Use one of: {', '.join(_METRICS)}."}}
            )
            return

        start_date = str(tool_parameters.get("start_date") or "").strip()
        end_date = str(tool_parameters.get("end_date") or "").strip()
        if not start_date or not end_date:
            start_date, end_date = default_month_range()

        # Similarweb only supports 'us' and 'ww' on these routes.
        sw_country = country if country in ("us", "ww") else "ww"

        try:
            client = AisaClient(self.runtime.credentials.get("aisa_api_key", ""))
            # Quote-first cost gate: every call below is price-quoted upstream
            # (free) and refused with an approval request when it meets the
            # user's threshold — see AisaClient._enforce_cost_guard.
            client.set_cost_guard(CostGuard.from_params("traffic_intel", metric, tool_parameters))
            if metric == "overview":
                result = client.request(
                    "GET", "/similarweb/website-traffic-snapshot",
                    params={"domain": domain, "country": sw_country},
                )
            elif metric == "trend":
                result = client.request(
                    "GET", "/similarweb/website-traffic-trend",
                    params={"domain": domain, "country": sw_country},
                )
            elif metric == "engagement":
                result = client.request(
                    "GET", "/similarweb/website/traffic-engagement",
                    params={
                        "domain": domain,
                        "start_date": start_date,
                        "end_date": end_date,
                        "metrics": "visits,pages_per_visit",
                        "country": sw_country,
                    },
                )
            elif metric == "ranking":
                result = client.request(
                    "GET", "/similarweb/website/ranking",
                    params={
                        "domain": domain,
                        "start_date": start_date,
                        "end_date": end_date,
                        "country": sw_country,
                    },
                )
            elif metric == "geographies":
                result = client.request(
                    "GET", "/similarweb/website-top-geographies",
                    params={"domain": domain},
                )
            elif metric == "demographics":
                # Upstream rule: start and end must be the SAME month.
                s, e = _resolve_window(client, domain, sw_country, tool_parameters, span=1)
                result = _dated_request(
                    client, "/similarweb/website/demographics",
                    {"domain": domain, "granularity": "monthly", "country": sw_country},
                    s, e, span=1,
                )
            elif metric == "similar_sites":
                # Upstream rule: EXACTLY 3 consecutive months, anchored to
                # Similarweb's most recent published window.
                s, e = _resolve_window(client, domain, sw_country, tool_parameters, span=3)
                result = _dated_request(
                    client, "/similarweb/website/similar-sites",
                    {"domain": domain, "limit": 20, "country": sw_country},
                    s, e, span=3,
                )
            elif metric == "technologies":
                # Upstream rule: start and end must be the SAME month.
                s, e = _resolve_window(client, domain, sw_country, tool_parameters, span=1)
                result = _dated_request(
                    client, "/similarweb/website/technologies",
                    {"domain": domain, "granularity": "monthly", "limit": 20,
                     "country": sw_country},
                    s, e, span=1,
                )
            elif metric == "popular_pages":
                result = client.request(
                    "GET", "/similarweb/website/popular-pages",
                    params={
                        "domain": domain,
                        "start_date": start_date,
                        "end_date": end_date,
                        "limit": 20,
                        "country": sw_country,
                    },
                )
            elif metric == "keyword_competitors":
                # Sites competing with this domain for the same search
                # keywords. The /search/ endpoints publish a FRESHER valid
                # window than the lag-2 default (verified live 2026-09-14),
                # so route through the self-healing dated flow.
                s, e = _resolve_window(client, domain, sw_country, tool_parameters, span=3)
                result = _dated_request(
                    client, "/similarweb/search/keyword-competitors",
                    {"domain": domain, "limit": 20, "country": sw_country},
                    s, e, span=3,
                )
            elif metric == "landing_pages":
                # Where search traffic actually lands on this domain.
                # Upstream rule (error 120, verified live 2026-09-15): unlike
                # keyword-competitors, this endpoint accepts AT MOST a one-
                # month interval — single-month window, like demographics.
                s, e = _resolve_window(client, domain, sw_country, tool_parameters, span=1)
                result = _dated_request(
                    client, "/similarweb/search/landing-pages",
                    {"domain": domain, "limit": 20, "country": sw_country},
                    s, e, span=1,
                )
            else:  # domain_authority — Ahrefs, two snapshot calls merged
                snapshot_date = today_str()
                rating = client.request(
                    "GET", "/ahrefs/site-explorer/domain-rating",
                    params={"target": domain, "date": snapshot_date},
                )
                site_metrics = client.request(
                    "GET", "/ahrefs/site-explorer/metrics",
                    params={"target": domain, "date": snapshot_date},
                )
                result = {"domain_rating": rating, "site_metrics": site_metrics}
        except AisaApprovalRequired as e:
            yield self.create_json_message(e.notice)
            yield self.create_text_message(e.notice["message"])
            return
        except AisaApiError as e:
            yield self.create_json_message({"error": {"code": e.code, "message": e.message}})
            return

        result = truncate_payload(result)
        payload: dict[str, Any] = {"metric": metric, "domain": domain, "result": result}
        cost = client.cost_disclosure()
        if cost:
            payload["cost"] = cost
        yield self.create_json_message(payload)
        yield self.create_text_message(
            generic_summary(f"Traffic intel — {metric} for {domain}:", result)
        )
