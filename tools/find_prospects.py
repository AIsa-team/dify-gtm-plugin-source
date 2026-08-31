from collections.abc import Generator
from typing import Any, List

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import AisaApiError, AisaClient, generic_summary, truncate_payload

_SEARCH_TYPES = ("people", "companies", "enrich_company")


def _split(raw: Any) -> List[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def _size_ranges(raw: Any) -> List[str]:
    """'11-50, 51-200' -> ['11,50', '51,200'] (Apollo's range format)."""
    ranges = []
    for part in _split(raw):
        bounds = part.replace("-", ",").split(",")
        if len(bounds) == 2 and all(b.strip().isdigit() for b in bounds):
            ranges.append(f"{bounds[0].strip()},{bounds[1].strip()}")
    return ranges


class FindProspectsTool(Tool):
    """B2B prospecting via Apollo — people search, company search, company enrichment."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        search_type = str(tool_parameters.get("search_type") or "people").strip().lower()
        keywords = str(tool_parameters.get("keywords") or "").strip()
        job_titles = _split(tool_parameters.get("job_titles"))
        locations = _split(tool_parameters.get("locations"))
        company_sizes = _size_ranges(tool_parameters.get("company_size"))
        domain = str(tool_parameters.get("domain") or "").strip()
        domain = domain.removeprefix("https://").removeprefix("http://").strip("/").removeprefix("www.")

        if search_type not in _SEARCH_TYPES:
            yield self._error(
                f"Unknown search_type '{search_type}'. Use one of: {', '.join(_SEARCH_TYPES)}."
            )
            return
        if search_type == "enrich_company" and not domain:
            yield self._error("search_type 'enrich_company' requires the 'domain' parameter.")
            return
        if search_type == "people" and not (keywords or job_titles or locations or domain):
            yield self._error(
                "search_type 'people' needs at least one filter: keywords, job_titles, "
                "locations, or domain."
            )
            return
        if search_type == "companies" and not (keywords or locations or company_sizes):
            yield self._error(
                "search_type 'companies' needs at least one filter: keywords, locations, "
                "or company_size."
            )
            return

        try:
            client = AisaClient(self.runtime.credentials.get("aisa_api_key", ""))
            if search_type == "people":
                params: dict[str, Any] = {"per_page": 10, "page": 1}
                if job_titles:
                    params["person_titles[]"] = job_titles
                if keywords:
                    params["q_keywords"] = keywords
                if locations:
                    params["person_locations[]"] = locations
                if company_sizes:
                    params["organization_num_employees_ranges[]"] = company_sizes
                if domain:
                    params["q_organization_domains_list[]"] = [domain]
                result = client.request(
                    "POST", "/apollo/mixed_people/api_search", params=params
                )
            elif search_type == "companies":
                params = {"per_page": 10, "page": 1}
                if keywords:
                    params["q_organization_keyword_tags[]"] = _split(keywords) or [keywords]
                if locations:
                    params["organization_locations[]"] = locations
                if company_sizes:
                    params["organization_num_employees_ranges[]"] = company_sizes
                if domain:
                    params["q_organization_domains_list[]"] = [domain]
                result = client.request(
                    "POST", "/apollo/mixed_companies/search", params=params
                )
            else:  # enrich_company
                result = client.request(
                    "GET", "/apollo/organizations/enrich", params={"domain": domain}
                )
        except AisaApiError as e:
            yield self.create_json_message({"error": {"code": e.code, "message": e.message}})
            return

        result = truncate_payload(result, max_field_chars=3000)
        yield self.create_json_message({"search_type": search_type, "result": result})
        yield self.create_text_message(
            generic_summary(f"Prospecting — {search_type}:", result, max_items=10)
        )

    def _error(self, message: str) -> ToolInvokeMessage:
        return self.create_json_message(
            {"error": {"code": "INVALID_INPUT", "message": message}}
        )
