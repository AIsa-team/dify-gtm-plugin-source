from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import AisaApiError, AisaClient, generic_summary, truncate_payload
from utils.gtm_common import dfs_location_name, semrush_database

_KEYWORD_METRICS = ("keyword_overview", "keyword_difficulty", "keyword_suggestions", "search_volume")
_DOMAIN_METRICS = ("domain_keywords", "domain_competitors", "backlinks_overview")

# Human-in-the-loop cost gate: these metrics never run without approved=true.
_PREMIUM_METRICS = {"keyword_difficulty": "$0.45", "domain_competitors": "$0.36"}


class KeywordSeoTool(Tool):
    """Keyword and SEO intelligence — Semrush + DataForSEO."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        metric = str(tool_parameters.get("metric") or "keyword_overview").strip().lower()
        keyword = str(tool_parameters.get("keyword") or "").strip()
        domain = str(tool_parameters.get("domain") or "").strip()
        domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
        country = str(tool_parameters.get("country") or "us").strip().lower()

        if metric not in _KEYWORD_METRICS + _DOMAIN_METRICS:
            yield self._error(
                f"Unknown metric '{metric}'. Use one of: "
                f"{', '.join(_KEYWORD_METRICS + _DOMAIN_METRICS)}."
            )
            return
        if metric in _KEYWORD_METRICS and not keyword:
            yield self._error(f"Metric '{metric}' requires the 'keyword' parameter.")
            return
        if metric in _DOMAIN_METRICS and not domain:
            yield self._error(f"Metric '{metric}' requires the 'domain' parameter.")
            return

        # Cost gate — refuses BEFORE any API call, so this response is free.
        if metric in _PREMIUM_METRICS and not tool_parameters.get("approved"):
            cost = _PREMIUM_METRICS[metric]
            notice = {
                "requires_approval": True,
                "metric": metric,
                "estimated_cost": cost,
                "message": (
                    f"'{metric}' is a premium call ({cost}). No data was fetched and "
                    "nothing was charged. Ask the user to approve the cost, then "
                    "retry this exact call with approved=true. If the user already "
                    "approved premium calls (in conversation or via a pre-approval "
                    "setting), retry with approved=true now."
                ),
            }
            yield self.create_json_message(notice)
            yield self.create_text_message(notice["message"])
            return

        database = semrush_database(country)
        location = dfs_location_name(country)

        try:
            client = AisaClient(self.runtime.credentials.get("aisa_api_key", ""))
            if metric == "keyword_overview":
                # Gateway drift (verified live 2026-09): this endpoint rejects
                # the documented 'database' param outright ("request does not
                # match the endpoint contract"). Omit it — the US database is
                # served by default. Other Semrush endpoints accept 'database'.
                result = client.request(
                    "GET", "/semrush/keyword-overview",
                    params={"phrase": keyword},
                )
            elif metric == "keyword_difficulty":
                # Semrush accepts up to 20 keywords separated by ';'
                phrase = ";".join(
                    k.strip() for k in keyword.replace(",", ";").split(";") if k.strip()
                )[:2000]
                result = client.request(
                    "GET", "/semrush/keyword-difficulty",
                    params={"phrase": phrase, "database": database},
                )
            elif metric == "keyword_suggestions":
                task: dict[str, Any] = {"keyword": keyword, "language_code": "en", "limit": 20}
                if location:
                    task["location_name"] = location
                result = client.request(
                    "POST", "/dataforseo/dataforseo_labs/google/keyword_suggestions/live",
                    data=[task],
                )
            elif metric == "search_volume":
                keywords = [k.strip() for k in keyword.replace(";", ",").split(",") if k.strip()]
                task = {"keywords": keywords[:100], "language_code": "en"}
                if location:
                    task["location_name"] = location
                result = client.request(
                    "POST", "/dataforseo/keywords_data/google_ads/search_volume/live",
                    data=[task],
                )
            elif metric == "domain_keywords":
                result = client.request(
                    "GET", "/semrush/domain-organic-keywords",
                    params={"domain": domain, "database": database},
                )
            elif metric == "domain_competitors":
                result = client.request(
                    "GET", "/semrush/domain-organic-competitors",
                    params={"domain": domain, "database": database},
                )
            else:  # backlinks_overview
                result = client.request(
                    "GET", "/semrush/backlinks-overview",
                    params={"target": domain},
                )
        except AisaApiError as e:
            yield self.create_json_message({"error": {"code": e.code, "message": e.message}})
            return

        result = truncate_payload(result)
        subject = keyword if metric in _KEYWORD_METRICS else domain
        payload: dict[str, Any] = {"metric": metric, "subject": subject, "result": result}
        summary = generic_summary(f"Keyword/SEO — {metric} for '{subject}':", result)
        if metric == "keyword_overview" and database != "us":
            notice = ("Note: keyword_overview currently serves the US database only "
                      "(upstream limitation); use search_volume for localized volumes.")
            payload["notice"] = notice
            summary += "\n" + notice
        yield self.create_json_message(payload)
        yield self.create_text_message(summary)

    def _error(self, message: str) -> ToolInvokeMessage:
        return self.create_json_message(
            {"error": {"code": "INVALID_INPUT", "message": message}}
        )
