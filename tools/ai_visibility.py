from collections.abc import Generator
from typing import Any, Dict, List, Optional

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.aisa_client import AisaApiError, AisaClient, generic_summary, truncate_payload
from utils.gtm_common import normalize_country

# Multi-backend answer-engine routing (verified live 2026-09):
# - LLM engines (chatgpt/gemini/perplexity/claude) -> DataForSEO
#   ai_optimization "live" endpoints. Oxylabs rejects Realtime for LLM
#   sources upstream ("use Push-Pull"), and AIsa has no async proxy.
# - google_search / google_ai_mode -> Oxylabs Realtime (works); AI Mode
#   falls back to DataForSEO's SERP endpoint if Oxylabs ever refuses.
_SOURCES = ("chatgpt", "gemini", "perplexity", "claude", "google_ai_mode", "google_search")

_DFS_ENGINES = {
    "chatgpt": "chat_gpt",
    "gemini": "gemini",
    "perplexity": "perplexity",
    "claude": "claude",
}

# Consumer-flagship defaults; validated against the free /models endpoints.
# A rejected name triggers a models-list refresh and one retry.
_DEFAULT_MODELS = {
    "chatgpt": "gpt-5.6-sol",
    "gemini": "gemini-3.8-flash",
    "perplexity": "sonar-pro",
    "claude": "claude-sonnet-5",
}

# Engines whose live endpoint accepts browse-the-web + country scoping.
_WEB_SEARCH = {"chatgpt", "gemini", "claude"}
_GEO_CAPABLE = {"chatgpt", "perplexity", "claude"}


def enrich_upstream_error(source: str, message: str) -> str:
    """Translate known upstream conditions into actionable guidance."""
    if "Push-Pull" in message or "Realtime integration" in message:
        return (
            f"The '{source}' route is unavailable upstream (provider requires "
            "async delivery for this source). Retry, or use another source."
        )
    return message


def _dfs_body(source: str, prompt: str, model: str, geo_iso: str) -> List[Dict[str, Any]]:
    task: Dict[str, Any] = {"user_prompt": prompt, "model_name": model}
    if source in _WEB_SEARCH:
        task["web_search"] = True
    if geo_iso and source in _GEO_CAPABLE:
        task["web_search_country_iso_code"] = geo_iso
    return [task]


def _dfs_result(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Unwrap the DataForSEO envelope; a rejected task is still HTTP 200."""
    tasks = resp.get("tasks") or []
    if not tasks:
        raise AisaApiError("DFS_EMPTY", "Empty response envelope from the data provider.")
    task = tasks[0]
    code = task.get("status_code")
    if code and int(code) >= 40000:
        raise AisaApiError(str(code), task.get("status_message", "Task rejected."))
    return {"result": task.get("result"), "cost": task.get("cost")}


def _first_model(models_resp: Dict[str, Any]) -> Optional[str]:
    for r in (models_resp.get("tasks") or [{}])[0].get("result") or []:
        if isinstance(r, dict):
            if r.get("model_name"):
                return r["model_name"]
            for it in r.get("items") or []:
                if isinstance(it, dict) and it.get("model_name"):
                    return it["model_name"]
    return None


class AiVisibilityTool(Tool):
    """AI answer-engine visibility (GEO/AEO) across six engines via two providers."""

    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        prompt = str(tool_parameters.get("prompt") or "").strip()
        source = str(tool_parameters.get("source") or "chatgpt").strip().lower()
        geo_location = str(tool_parameters.get("geo_location") or "").strip()
        model = str(tool_parameters.get("model") or "").strip()

        if not prompt:
            yield self._error("The 'prompt' parameter is required — the question to ask the AI engine.")
            return
        if source not in _SOURCES:
            yield self._error(f"Unknown source '{source}'. Use one of: {', '.join(_SOURCES)}.")
            return

        try:
            client = AisaClient(self.runtime.credentials.get("aisa_api_key", ""))
            if source in _DFS_ENGINES:
                result = self._invoke_llm_engine(client, source, prompt, model, geo_location)
            else:
                result = self._invoke_google(client, source, prompt, geo_location)
        except AisaApiError as e:
            yield self.create_json_message(
                {"error": {"code": e.code,
                           "message": enrich_upstream_error(source, e.message)}}
            )
            return

        result = truncate_payload(result)
        yield self.create_json_message({"source": source, "prompt": prompt, "result": result})
        yield self.create_text_message(
            generic_summary(f"AI visibility — how {source} answers '{prompt[:80]}':", result)
        )

    def _invoke_llm_engine(self, client, source, prompt, model, geo_location):
        engine = _DFS_ENGINES[source]
        path = f"/dataforseo/ai_optimization/{engine}/llm_responses/live"
        geo_iso = normalize_country(geo_location).upper() if geo_location else ""
        chosen = model or _DEFAULT_MODELS[source]
        try:
            resp = client.request(
                "POST", path, data=_dfs_body(source, prompt, chosen, geo_iso),
                timeout=110, retries=0,
            )
            return _dfs_result(resp)
        except AisaApiError as e:
            if "model" not in e.message.lower():
                raise
            # Model catalog rotated: refresh from the free models endpoint, retry once.
            models = client.request(
                "GET", f"/dataforseo/ai_optimization/{engine}/llm_responses/models",
                timeout=30, retries=0,
            )
            fallback = _first_model(models)
            if not fallback or fallback == chosen:
                raise
            resp = client.request(
                "POST", path, data=_dfs_body(source, prompt, fallback, geo_iso),
                timeout=110, retries=0,
            )
            out = _dfs_result(resp)
            out["model_fallback"] = f"default '{chosen}' rejected; used '{fallback}'"
            return out

    def _invoke_google(self, client, source, prompt, geo_location):
        body: Dict[str, Any] = {"source": source, "parse": True,
                                "query": prompt, "render": "html"}
        if geo_location:
            body["geo_location"] = geo_location
        try:
            return client.request("POST", "/oxylabs/ai-search", data=body,
                                  timeout=110, retries=0)
        except AisaApiError as e:
            fallback_ok = source == "google_ai_mode" and (
                "Push-Pull" in e.message or "Realtime" in e.message or e.code in ("422",)
            )
            if not fallback_ok:
                raise
            task: Dict[str, Any] = {"keyword": prompt, "language_code": "en"}
            if geo_location:
                task["location_name"] = geo_location
            resp = client.request(
                "POST", "/dataforseo/serp/google/ai_mode/live/advanced",
                data=[task], timeout=110, retries=0,
            )
            out = _dfs_result(resp)
            out["provider_fallback"] = "oxylabs unavailable; served via dataforseo"
            return out

    def _error(self, message: str) -> ToolInvokeMessage:
        return self.create_json_message(
            {"error": {"code": "INVALID_INPUT", "message": message}}
        )
