from collections.abc import Generator
from typing import Any, Dict, List

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import AisaApiError, AisaClient, find_results, truncate_payload

_VALID_MODES = ("search", "extract", "crawl", "map")


class WebResearchTool(Tool):
    """Tavily-backed web research through the AIsa unified API."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        mode = str(tool_parameters.get("mode") or "search").strip().lower()
        query = str(tool_parameters.get("query") or "").strip()
        urls = _parse_urls(tool_parameters.get("urls"))

        if mode not in _VALID_MODES:
            yield self._error(f"Unknown mode '{mode}'. Use one of: {', '.join(_VALID_MODES)}.")
            return
        if mode == "search" and not query:
            yield self._error("Mode 'search' requires the 'query' parameter.")
            return
        if mode in ("extract", "crawl", "map") and not urls:
            yield self._error(f"Mode '{mode}' requires the 'urls' parameter.")
            return

        try:
            max_depth = max(1, min(3, int(tool_parameters.get("max_depth") or 2)))
        except (TypeError, ValueError):
            max_depth = 2

        try:
            client = AisaClient(self.runtime.credentials.get("aisa_api_key", ""))
            if mode == "search":
                result = client.tavily_search(query)
            elif mode == "extract":
                result = client.tavily_extract(urls)
            elif mode == "crawl":
                result = client.tavily_crawl(urls[0], max_depth=max_depth)
            else:  # map
                result = client.tavily_map(urls[0])
        except AisaApiError as e:
            yield self._error(e.message, code=e.code)
            return

        result = truncate_payload(result)
        yield self.create_json_message({"mode": mode, "result": result})
        yield self.create_text_message(_summarize(mode, query, urls, result))

    def _error(self, message: str, code: str = "INVALID_INPUT") -> ToolInvokeMessage:
        return self.create_json_message({"error": {"code": code, "message": message}})


def _parse_urls(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        candidates = [str(u) for u in raw]
    else:
        candidates = str(raw).replace("\n", ",").split(",")
    return [u.strip() for u in candidates if u.strip()]


def _summarize(mode: str, query: str, urls: List[str], result: Dict[str, Any]) -> str:
    """Compact, agent-friendly text view of the raw JSON result."""
    items = find_results(result)

    if mode == "search":
        lines = [f"Web search results for: {query}"]
        for i, item in enumerate(items[:8], 1):
            title = str(item.get("title") or item.get("url") or "untitled").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("content") or item.get("snippet") or "").strip()
            if len(snippet) > 300:
                snippet = snippet[:300] + "..."
            lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
        if not items:
            lines.append("(no results found)")
        return "\n".join(lines)

    if mode == "extract":
        lines = [f"Extracted content from {len(urls)} URL(s):"]
        for item in items[: len(urls) or 5]:
            url = str(item.get("url") or "").strip()
            content = str(item.get("raw_content") or item.get("content") or "").strip()
            lines.append(f"- {url}: {len(content)} chars extracted")
        if not items:
            lines.append("(no content returned — see JSON payload)")
        return "\n".join(lines)

    if mode == "crawl":
        return (
            f"Crawled {urls[0]}: {len(items)} page(s) returned. "
            "Full page content is in the JSON payload."
        )

    # map
    mapped = [str(item.get("url") or item) for item in items] if items else []
    if not mapped and isinstance(result, dict):
        raw = result.get("results") or result.get("urls") or []
        if isinstance(raw, list):
            mapped = [str(u) for u in raw]
    preview = "\n".join(f"- {u}" for u in mapped[:20])
    suffix = f"\n(+{len(mapped) - 20} more in JSON payload)" if len(mapped) > 20 else ""
    return f"Site map of {urls[0]}: {len(mapped)} URL(s) found.\n{preview}{suffix}"
