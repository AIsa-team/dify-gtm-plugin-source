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
    # regression: mixed-case candidate ('userName') against creator-style rows
    s3 = generic_summary("T:", {"results": [{"userName": "mreflow", "subscribers": 1}]})
    check("mixed-case candidate keys do not crash", "mreflow" in s3)
    s4 = generic_summary("T:", {"results": [{"username": "a", "userName": "a"}]})
    check("duplicate case-variant keys deduped", s4.count("=a") == 1)


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
        check("spaces encoded as %20, not +", "phrase=AI%20agents" in captured["url"])
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


def test_contract_fallback():
    import utils.aisa_client as m

    c = m.AisaClient("k")
    # registry-driven minimal subsets
    check("minimal params drops optionals",
          c._minimal_params("/semrush/keyword-overview", {"phrase": "x", "database": "us"})
          == {"phrase": "x"})
    check("no fallback when nothing to drop",
          c._minimal_params("/semrush/keyword-overview", {"phrase": "x"}) is None)
    check("no fallback for unregistered endpoints (Apollo searches)",
          c._minimal_params("/apollo/mixed_people/api_search", {"per_page": 10}) is None)

    # end-to-end: contract 400 on first send, success on required-only retry
    calls = []

    def fake_once(method, endpoint, params=None, data=None, *a, **kw):
        calls.append(dict(params or {}))
        if "database" in (params or {}):
            raise m.AisaApiError("400", "request does not match the endpoint contract")
        return {"results": [1]}

    c._request_once = fake_once
    out = c.request("GET", "/semrush/keyword-overview",
                    params={"phrase": "seotools", "database": "us"})
    check("fallback retried with required-only params",
          len(calls) == 2 and calls[1] == {"phrase": "seotools"})
    check("fallback annotates the result",
          out["_contract_fallback"]["dropped_params"] == ["database"])

    def fake_auth_fail(*a, **kw):
        raise m.AisaAuthError("401", "invalid api key")

    c._request_once = fake_auth_fail
    try:
        c.request("GET", "/semrush/keyword-overview",
                  params={"phrase": "x", "database": "us"})
        raise AssertionError("auth error swallowed")
    except m.AisaAuthError:
        check("non-contract errors are not retried", True)


def test_audit_wiring():
    import json as _json
    baseline = _json.load(open(os.path.join(ROOT, "tests", "contracts_baseline.json")))
    check("baseline covers 36 tools", len(baseline) == 36, f"got {len(baseline)}")
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import contract_audit
    check("audit SENT map covers every baseline tool",
          set(contract_audit.SENT) == set(baseline))


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

    from utils.gtm_common import approval_notice, parse_threshold
    check("threshold parses and defaults", parse_threshold("0.10") == 0.10
          and parse_threshold(None) == 0.30 and parse_threshold("junk") == 0.30)
    check("default threshold gates difficulty",
          approval_notice("keyword_seo", "keyword_difficulty", {})["estimated_cost"] == "$0.45")
    check("default threshold passes domain_authority (0.26 < 0.30)",
          approval_notice("traffic_intel", "domain_authority", {}) is None)
    check("low threshold gates dated similarweb metrics",
          approval_notice("traffic_intel", "similar_sites", {"approval_threshold": 0.10}) is not None)
    check("free metrics never gated even at threshold 0",
          approval_notice("traffic_intel", "overview", {"approval_threshold": 0}) is None)
    check("approved=true always passes",
          approval_notice("keyword_seo", "keyword_difficulty", {"approved": True}) is None)

    ks = load("keyword_seo")
    tool = object.__new__(ks.KeywordSeoTool)
    tool.create_json_message = lambda d: ("json", d)
    tool.create_text_message = lambda t: ("text", t)
    out = list(tool._invoke({"metric": "keyword_difficulty", "keyword": "crm; helpdesk"}))
    check("premium metric without approval is refused (no API call)",
          out[0][1].get("requires_approval") is True and "$0.45" in out[0][1]["estimated_cost"])
    out = list(tool._invoke({"metric": "domain_competitors", "domain": "x.com"}))
    check("domain_competitors gated too", out[0][1].get("requires_approval") is True)
    try:
        out = list(tool._invoke({"metric": "keyword_overview", "keyword": "crm"}))
        gated = isinstance(out[0][1], dict) and out[0][1].get("requires_approval")
    except AttributeError:
        gated = False  # reached the client stage (stub has no runtime) => passed the gate
    check("cheap metrics not gated", not gated)

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

    from utils.aisa_client import AisaApiError

    class StubClient:
        def __init__(self, latest="2026-07", fail_windows=0):
            self.calls, self.latest, self.fail = [], latest, fail_windows

        def request(self, method, path, params=None, **kw):
            self.calls.append((path, dict(params or {})))
            if "snapshot" in path:
                return {"meta": {"end_date": self.latest}}
            if self.fail > 0:
                self.fail -= 1
                raise AisaApiError("400", "Dates not in range (error 101)")
            return {"data": [1]}

    # single-month window anchored to latest published month
    c = StubClient()
    s, e = ti._resolve_window(c, "x.com", "ww", {}, span=1)
    check("span=1 window is one month at latest", (s, e) == ("2026-07", "2026-07"))
    s, e = ti._resolve_window(c, "x.com", "ww", {}, span=3)
    check("span=3 window covers 3 months", (s, e) == ("2026-05", "2026-07"))
    s, e = ti._resolve_window(c, "x.com", "ww", {"start_date": "2026-01", "end_date": "2026-01"}, span=1)
    check("user dates respected verbatim", (s, e) == ("2026-01", "2026-01"))

    # window-rejection retry advances one month, preserves span
    c = StubClient(fail_windows=1)
    ti._dated_request(c, "/similarweb/website/demographics", {"domain": "x.com"},
                      "2026-06", "2026-06", span=1)
    retry = c.calls[-1][1]
    check("window retry advances one month, same span",
          retry["start_date"] == "2026-07" and retry["end_date"] == "2026-07")

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
               test_request_headers, test_contract_fallback, test_audit_wiring,
               test_gtm_common, test_tool_helpers, test_yaml_wiring, test_readme_rules]:
        print(fn.__name__)
        fn()
    print(f"\nAll {PASSED} checks passed.")
