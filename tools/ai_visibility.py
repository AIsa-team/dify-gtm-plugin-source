from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import AisaApiError, AisaClient, generic_summary, truncate_payload

_SOURCES = ("chatgpt", "gemini", "perplexity", "google_ai_mode", "google_search")

# Per the AIsa contract: Google-type sources (google_search AND google_ai_mode)
# take 'query'; the AI engines take 'prompt', with per-engine length caps.
_PROMPT_CAPS = {"chatgpt": 4000, "gemini": 8000}


def _prompt_field(source: str, prompt: str) -> dict:
    if source in ("google_search", "google_ai_mode"):
        return {"query": prompt}
    cap = _PROMPT_CAPS.get(source)
    return {"prompt": prompt[:cap] if cap else prompt}


class AiVisibilityTool(Tool):
    """AI answer-engine visibility (GEO/AEO) via Oxylabs — see how AI engines answer a prompt."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        prompt = str(tool_parameters.get("prompt") or "").strip()
        source = str(tool_parameters.get("source") or "chatgpt").strip().lower()
        geo_location = str(tool_parameters.get("geo_location") or "").strip()

        if not prompt:
            yield self._error("The 'prompt' parameter is required — the question to ask the AI engine.")
            return
        if source not in _SOURCES:
            yield self._error(f"Unknown source '{source}'. Use one of: {', '.join(_SOURCES)}.")
            return

        body: dict[str, Any] = {"source": source, "parse": True}
        body.update(_prompt_field(source, prompt))
        if geo_location:
            body["geo_location"] = geo_location

        try:
            client = AisaClient(self.runtime.credentials.get("aisa_api_key", ""))
            # Answer engines render a full session upstream; allow extra time.
            result = client.request("POST", "/oxylabs/ai-search", data=body, timeout=110)
        except AisaApiError as e:
            yield self.create_json_message({"error": {"code": e.code, "message": e.message}})
            return

        result = truncate_payload(result)
        yield self.create_json_message({"source": source, "prompt": prompt, "result": result})
        yield self.create_text_message(
            generic_summary(f"AI visibility — how {source} answers '{prompt[:80]}':", result)
        )

    def _error(self, message: str) -> ToolInvokeMessage:
        return self.create_json_message(
            {"error": {"code": "INVALID_INPUT", "message": message}}
        )
