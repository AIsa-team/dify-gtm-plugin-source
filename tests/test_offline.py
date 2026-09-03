"""Offline test suite for the AIsa Go-to-Market plugin.

Runs with plain Python — no pytest, no network, no API key:

    python3 tests/test_offline.py

Covers the shared client's error handling and parsing, the GTM helpers,
tool parameter builders, and YAML/provider cross-references.
"""

import json
import os
import sys
import types
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASSED = 0


def check(name, condition, detail=""):
    global PASSED
    if not condition:
        raise AssertionError(f"FAIL: {name} {detail}")
    PASSED += 1
    print(f"  ok  {name}")


def stub_dify():
    """Make tool modules importable without the dify_plugin SDK."""
    if "dify_plugin" in sys.modules:
        return
    dp = types.ModuleType("dify_plugin")
    dp.Tool = type("Tool", (), {})
    dp.ToolProvider = type("ToolProvider", (), {})
    ent = types.ModuleType("dify_plugin.entities")
    ent_tool = types.ModuleType("dify_plugin.entities.tool")
    ent_tool.ToolInvokeMessage = type("ToolInvokeMessage", (), {})
    err = types.ModuleType("dify_plugin.errors")
    err_tool = types.ModuleType("dify_plugin.errors.tool")
    err_tool.ToolProviderCredentialValidationError = type(
        "ToolProviderCredentialValidationError", (Exception,), {}
    )
    sys.modules.update({
        "dify_plugin": dp,
        "dify_plugin.entities": ent,
        "dify_plugin.entities.tool": ent_tool,
        "dify_plugin.errors": err,
        "dify_plugin.errors.tool": err_tool,
    })


def test_client_errors():
    from utils.aisa_client import (
        AisaApiError, AisaAuthError, AisaClient, AisaCreditError,
    )

    try:
        AisaClient("")
        raise AssertionError("empty key accepted")
    except AisaAuthError as e:
        check("missing key raises AisaAuthError with plan link", "aisa.one" in str(e))

    c = AisaClient("test-key")
    try:
        c._check_body({"success": False, "error": {"code": "401", "message": "bad key"}})
        raise AssertionError("auth error body accepted")
    except AisaAuthError:
        check("error-in-200-body -> AisaAuthError", True)

    try:
        c._check_body({"error": {"code": "QUOTA_EXCEEDED", "message": "no credit"}})
        raise AssertionError("credit error body accepted")
    except AisaCreditError as e:
        check("quota error -> AisaCreditError with top-up link", "aisa.one" in str(e))

    try:
        c._check_body({"error": "api endpoint not found"})
        raise AssertionError("string error body accepted")
    except AisaApiError:
        check("string error body -> AisaApiError", True)

    check("clean body passes through", c._check_body({"results": [1]}) == {"results": [1]})


def test_delimited_text():
    from utils.aisa_client import _parse_delimited_text, find_results

    r = _parse_delimited_text(
        "Keyword;Search Volume;CPC;Competition\nai agents;74000;3.51;0.12"
    )
    check("semrush header row parsed", r["results"][0]["Keyword"] == "ai agents")
    check("find_results sees delimited rows", len(find_results(r)) == 1)

    r2 = _parse_delimited_text("seo tools;550000;7.79;0.03;124")
    check("headerless row parsed positionally", r2["results"][0]["col_1"] == "550000")

    r3 = _parse_delimited_text("ERROR :: nothing found")
    check("non-delimited text kept as raw", r3["results"] == [] and r3["raw_text"])


def test_truncation_and_summary():
    from utils.aisa_client import generic_summary, truncate_payload

    t = truncate_payload({"a": "x" * 9000}, max_field_chars=100)
    check("long fields truncated with marker", "truncated" in t["a"] and len(t["a"]) < 200)

    s = generic_summary("T:", {"data": {"people": [{"name": "Jane", "title": "CTO"}]}})
    check("summary finds nested records", "Jane" in s)
    s2 = generic_summary("T:", {"results": [{"Keyword": "ai agents"}]})
    check("summary matches keys case-insensitively", "ai agents" in s2)


def test_request_headers():
    import utils.aisa_client as m

    captured = {}

    class FakeResp:
        headers = {"Content-Type": "application/json"}

        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    original = urllib.request.urlopen

    def fake_urlopen(req, timeout=None):
        captured["ct"] = req.headers.get("Content-type")
        captured["url"] = req.full_url
        return FakeResp()

    urllib.request.urlopen = fake_urlopen
    try:
        c = m.AisaClient("k")
        c.request("GET", "/semrush/keyword-overview", params={"phrase": "AI agents"})
        check("GET sends no Content-Type", captured["ct"] is None)
        check("GET query encoded", "phrase=AI+agents" in captured["url"])
        c.request("POST", "/tavily/search", data={"query": "x"})
        check("POST sends Content-Type json", captured["ct"] == "application/json")
        c.request("POST", "/apollo/mixed_people/api_search",
                  params={"person_titles[]": ["CEO", "CTO"]})
        check("array params expand to repeated keys",
              captured["url"].count("person_titles%5B%5D") == 2)
        c.credits_balance()
        check("credits balance uses /v1 account base",
              captured["url"] == "https://api.aisa.one/v1/credits/balance")
    finally:
        urllib.request.urlopen = original


def test_gtm_common():
    from utils.gtm_common import (
        default_month_range, dfs_location_name, normalize_country, semrush_database,
    )

    s, e = default_month_range()
    check("month range well-formed", len(s) == 7 and len(e) == 7 and s < e)
    check("country name -> code", normalize_country("United States") == "us")
    check("gb -> uk", semrush_database("GB") == "uk")
    check("unknown -> us fallback", normalize_country("Neverland") == "us")
    check("EU markets mapped (pl)", dfs_location_name("pl") == "Poland")
    check("EU markets mapped (Czechia)", dfs_location_name("Czechia") == "Czech Republic")


def test_tool_helpers():
    stub_dify()
    import importlib.util

    def load(name):
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(ROOT, "tools", f"{name}.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    fp = load("find_prospects")
    check("title splitting", fp._split("CEO, VP Marketing") == ["CEO", "VP Marketing"])
    check("size ranges to Apollo format", fp._size_ranges("11-50, 51-200") == ["11,50", "51,200"])
    check("garbage size ranges dropped", fp._size_ranges("big companies") == [])

    av = load("ai_visibility")
    check("google_ai_mode uses query + render",
          av._source_params("google_ai_mode", "x") == {"query": "x", "render": "html"})
    check("google_search uses query + render",
          av._source_params("google_search", "x") == {"query": "x", "render": "html"})
    check("chatgpt uses capped prompt + web search",
          av._source_params("chatgpt", "p" * 5000) == {"prompt": "p" * 4000, "search": True})
    check("gemini capped at 8000, no search flag",
          av._source_params("gemini", "g" * 9000) == {"prompt": "g" * 8000})
    check("perplexity uses prompt, uncapped",
          av._source_params("perplexity", "hello") == {"prompt": "hello"})

    ti = load("traffic_intel")
    check("latest month from snapshot meta",
          ti._latest_published_month({"meta": {"end_date": "2026-07"}, "data": {}}) == "2026-07")
    check("latest month falls back to data.month",
          ti._latest_published_month({"data": {"month": "2026-07"}}) == "2026-07")
    check("latest month empty on junk", ti._latest_published_month({"x": 1}) == "")

    from utils.gtm_common import shift_month_str
    check("month shift back", shift_month_str("2026-07", -2) == "2026-05")
    check("month shift across year", shift_month_str("2026-01", -2) == "2025-11")
    check("month shift forward", shift_month_str("2026-12", 1) == "2027-01")


def test_yaml_wiring():
    import yaml

    prov = yaml.safe_load(open(os.path.join(ROOT, "provider", "go-to-market.yaml")))
    tools = prov["tools"]
    check("7 tools registered", len(tools) == 7, f"got {len(tools)}")
    for t in tools:
        td = yaml.safe_load(open(os.path.join(ROOT, t)))
        src = os.path.join(ROOT, td["extra"]["python"]["source"])
        check(f"{td['identity']['name']} source exists", os.path.exists(src))
    creds = prov["credentials_for_provider"]["aisa_api_key"]
    check("credential links to GTM plan page",
          "aisa.one/solutions/go-to-market" in creds["url"])
    manifest = yaml.safe_load(open(os.path.join(ROOT, "manifest.yaml")))
    check("manifest points at provider yaml",
          manifest["plugins"]["tools"] == ["provider/go-to-market.yaml"])
    check("manifest has required repo field",
          manifest.get("repo", "").startswith("https://github.com/AIsa-team/"))
    check("manifest has required contact field", "@" in manifest.get("contact", ""))
    check("manifest sets minimum_dify_version",
          isinstance(manifest["meta"].get("minimum_dify_version"), str))
    check("localized README uses dot naming",
          os.path.exists(os.path.join(ROOT, "README.zh_Hans.md"))
          and not os.path.exists(os.path.join(ROOT, "README_zh_Hans.md")))


def test_readme_rules():
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    has_cjk = any("一" <= ch <= "鿿" for ch in readme)
    check("README.md contains no Chinese characters", not has_cjk)
    check("README promotes the GTM plan", "aisa.one/solutions/go-to-market" in readme)
    privacy = open(os.path.join(ROOT, "PRIVACY.md"), encoding="utf-8").read()
    check("PRIVACY.md is not the template", "Please fill in" not in privacy)


if __name__ == "__main__":
    for fn in [test_client_errors, test_delimited_text, test_truncation_and_summary,
               test_request_headers, test_gtm_common, test_tool_helpers,
               test_yaml_wiring, test_readme_rules]:
        print(fn.__name__)
        fn()
    print(f"\nAll {PASSED} checks passed.")
