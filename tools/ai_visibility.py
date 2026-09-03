from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import AisaApiError, AisaClient, generic_summary, truncate_payload

_SOURCES = ("chatgpt", "gemini", "perplexity", "google_ai_mode", "google_search")

# Per the AIsa/Oxylabs contract, each source expects a specific parameter set:
# - google_search / google_ai_mode: 'query' + render="html" (page must be
#   rendered before parsing; omitting render is rejected with a 400)
# - chatgpt: 'prompt' (max 4000 chars) + search=true (browse the web before
#   answering — matches what real users' ChatGPT does, and yields citations)
# - gemini: 'prompt' (max 8000 chars); perplexity: 'prompt'
_PROMPT_CAPS = {"chatgpt": 4000, "gemini": 8000}


def _source_params(source: str, prompt: str) -> dict:
    if source in ("google_search", "google_ai_mode"):
        return {"query": prompt, "render": "html"}
    cap = _PROMPT_CAPS.get(source)
    params: dict = {"prompt": prompt[:cap] if cap else prompt}
    if source == "chatgpt":
        params["search"] = True
    return params


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
        body.update(_source_params(source, prompt))
        if geo_location:
            body["geo_location"] = geo_location

        try:
            client = AisaClient(self.runtime.credentials.get("aisa_api_key", ""))
            # Answer engines render a full session upstream; allow extra time.
            # retries=0: a second 110s attempt cannot fit inside the plugin
            # runtime's request cap — fail honestly instead.
            result = client.request(
                "POST", "/oxylabs/ai-search", data=body, timeout=110, retries=0
            )
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
