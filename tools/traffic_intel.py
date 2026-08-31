from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import AisaApiError, AisaClient, generic_summary, truncate_payload
from utils.gtm_common import default_month_range, today_str

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
                result = client.request(
                    "GET", "/similarweb/website/demographics",
                    params={
                        "domain": domain,
                        "start_date": start_date,
                        "end_date": end_date,
                        "granularity": "monthly",
                        "country": sw_country,
                    },
                )
            elif metric == "similar_sites":
                result = client.request(
                    "GET", "/similarweb/website/similar-sites",
                    params={
                        "domain": domain,
                        "start_date": start_date,
                        "end_date": end_date,
                        "limit": 20,
                        "country": sw_country,
                    },
                )
            elif metric == "technologies":
                result = client.request(
                    "GET", "/similarweb/website/technologies",
                    params={
                        "domain": domain,
                        "start_date": start_date,
                        "end_date": end_date,
                        "granularity": "monthly",
                        "limit": 20,
                        "country": sw_country,
                    },
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
        except AisaApiError as e:
            yield self.create_json_message({"error": {"code": e.code, "message": e.message}})
            return

        result = truncate_payload(result)
        yield self.create_json_message({"metric": metric, "domain": domain, "result": result})
        yield self.create_text_message(
            generic_summary(f"Traffic intel — {metric} for {domain}:", result)
        )
