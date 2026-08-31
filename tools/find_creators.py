from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import AisaApiError, AisaClient, generic_summary, truncate_payload

_PLATFORMS = ("youtube", "tiktok")


class FindCreatorsTool(Tool):
    """Creator/influencer discovery via WaveInflu."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        mode = str(tool_parameters.get("mode") or "similar").strip().lower()
        profile_url = str(tool_parameters.get("profile_url") or "").strip()
        platform = str(tool_parameters.get("platform") or "youtube").strip().lower()
        content_direction = str(tool_parameters.get("content_direction") or "").strip()

        try:
            limit = max(1, min(50, int(tool_parameters.get("limit") or 10)))
        except (TypeError, ValueError):
            limit = 10

        if mode not in ("similar", "email"):
            yield self._error("Mode must be 'similar' (find similar creators) or 'email' (contact lookup).")
            return
        if not profile_url:
            yield self._error("The 'profile_url' parameter is required — a creator's profile URL.")
            return
        if mode == "similar" and platform not in _PLATFORMS:
            yield self._error(f"Platform must be one of: {', '.join(_PLATFORMS)}.")
            return

        try:
            client = AisaClient(self.runtime.credentials.get("aisa_api_key", ""))
            if mode == "similar":
                body: dict[str, Any] = {
                    "platform": platform,
                    "seedProfileUrl": profile_url,
                    "limit": limit,
                }
                if content_direction:
                    body["contentDirection"] = content_direction
                result = client.request("POST", "/waveinflu/similar", data=body)
            else:  # email
                result = client.request(
                    "POST", "/waveinflu/email-lookup", data={"url": profile_url}
                )
        except AisaApiError as e:
            yield self.create_json_message({"error": {"code": e.code, "message": e.message}})
            return

        result = truncate_payload(result)
        yield self.create_json_message({"mode": mode, "profile_url": profile_url, "result": result})
        yield self.create_text_message(
            generic_summary(f"Creator discovery — {mode} for {profile_url}:", result, max_items=10)
        )

    def _error(self, message: str) -> ToolInvokeMessage:
        return self.create_json_message(
            {"error": {"code": "INVALID_INPUT", "message": message}}
        )
