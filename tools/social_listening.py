from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import AisaApiError, AisaClient, generic_summary, truncate_payload

_PLATFORMS = ("x", "reddit", "instagram", "pinterest", "youtube")
_PROFILE_PLATFORMS = ("x", "instagram")


class SocialListeningTool(Tool):
    """Read-only social listening across X, Reddit, Instagram, Pinterest, YouTube."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        platform = str(tool_parameters.get("platform") or "").strip().lower()
        mode = str(tool_parameters.get("mode") or "search").strip().lower()
        query = str(tool_parameters.get("query") or "").strip()
        handle = str(tool_parameters.get("handle") or "").strip().lstrip("@")
        subreddit = str(tool_parameters.get("subreddit") or "").strip()
        subreddit = subreddit.removeprefix("r/")

        if platform == "twitter":
            platform = "x"
        if platform not in _PLATFORMS:
            yield self._error(
                f"Unknown platform '{platform}'. Use one of: {', '.join(_PLATFORMS)}. "
                "(TikTok is not currently available through the AIsa API.)"
            )
            return
        if mode not in ("search", "profile"):
            yield self._error("Mode must be 'search' or 'profile'.")
            return
        if mode == "profile" and platform not in _PROFILE_PLATFORMS:
            yield self._error(
                f"Mode 'profile' is only available for: {', '.join(_PROFILE_PLATFORMS)}."
            )
            return
        if mode == "search" and not query:
            yield self._error("Mode 'search' requires the 'query' parameter.")
            return
        if mode == "profile" and not handle:
            yield self._error("Mode 'profile' requires the 'handle' parameter.")
            return

        try:
            client = AisaClient(self.runtime.credentials.get("aisa_api_key", ""))
            if platform == "x":
                if mode == "profile":
                    result = client.request(
                        "GET", "/twitter/user/info", params={"userName": handle}
                    )
                else:
                    result = client.request(
                        "GET", "/twitter/tweet/advanced_search",
                        params={"query": query, "queryType": "Latest"},
                    )
            elif platform == "reddit":
                if subreddit:
                    result = client.request(
                        "GET", "/reddit/subreddit/search",
                        params={"subreddit": subreddit, "query": query, "sort": "relevance"},
                    )
                else:
                    result = client.request(
                        "GET", "/reddit/search",
                        params={"query": query, "sort": "relevance", "trim": "true"},
                    )
            elif platform == "instagram":
                if mode == "profile":
                    result = client.request(
                        "GET", "/instagram/profile",
                        params={"handle": handle, "trim": "true"},
                    )
                else:
                    result = client.request(
                        "GET", "/instagram/reels/search", params={"query": query}
                    )
            elif platform == "pinterest":
                result = client.request(
                    "GET", "/pinterest/search", params={"query": query, "trim": "true"}
                )
            else:  # youtube
                result = client.request(
                    "GET", "/youtube/search", params={"engine": "youtube", "q": query}
                )
        except AisaApiError as e:
            yield self.create_json_message({"error": {"code": e.code, "message": e.message}})
            return

        result = truncate_payload(result, max_field_chars=3000)
        subject = handle if mode == "profile" else query
        yield self.create_json_message(
            {"platform": platform, "mode": mode, "subject": subject, "result": result}
        )
        yield self.create_text_message(
            generic_summary(f"Social listening — {platform} {mode} for '{subject}':", result)
        )

    def _error(self, message: str) -> ToolInvokeMessage:
        return self.create_json_message(
            {"error": {"code": "INVALID_INPUT", "message": message}}
        )
