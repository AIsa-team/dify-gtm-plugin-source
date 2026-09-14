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

    code, msg = AisaClient._extract_error(
        {"meta": {"status": "error", "error_code": 101,
                  "error_message": "Dates not in range."}}, "400")
    check("similarweb meta-envelope errors surfaced (window self-heal depends on it)",
          code == "101" and "Dates not in range" in msg)


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

        # raw socket timeouts must become the normal error envelope
        attempts = {"n": 0}

        def timeout_urlopen(req, timeout=None):
            attempts["n"] += 1
            raise TimeoutError("The read operation timed out")

        urllib.request.urlopen = timeout_urlopen
        from utils.aisa_client import AisaApiError as _E
        try:
            c.request("POST", "/oxylabs/ai-search", data={"source": "chatgpt"},
                      retries=0, retry_delay_seconds=0)
            raise AssertionError("timeout not converted")
        except _E as e:
            check("read timeout -> AisaApiError TIMEOUT", e.code == "TIMEOUT")
        check("retries=0 means exactly one attempt", attempts["n"] == 1)

        def oserror_urlopen(req, timeout=None):
            raise ConnectionResetError("peer reset")

        urllib.request.urlopen = oserror_urlopen
        try:
            c.request("GET", "/youtube/search", params={"engine": "youtube", "q": "x"},
                      retries=0, retry_delay_seconds=0)
            raise AssertionError("oserror not converted")
        except _E as e:
            check("raw OSError -> NETWORK_ERROR envelope", e.code == "NETWORK_ERROR")
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
    check("baseline covers 44 tools", len(baseline) == 44, f"got {len(baseline)}")
    check("baseline uses the BATCH_GET_SCHEMA-era fields",
          all({"schema_sha256", "pitfalls_sha256", "properties", "required"}
              <= set(entry) for entry in baseline.values()))
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import contract_audit
    check("audit SENT map matches the recorded baseline exactly",
          set(contract_audit.SENT) == set(baseline))
    check("audit targets the current router meta-tool",
          "AISA_BATCH_GET_SCHEMA" in open(
              os.path.join(ROOT, "tests", "contract_audit.py")).read())
    check("quote canaries defined (the gate has no static fallback)",
          len(contract_audit.QUOTE_CANARIES) >= 3)


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

    from utils.gtm_common import parse_threshold
    check("threshold parses and defaults", parse_threshold("0.10") == 0.10
          and parse_threshold(None) == 0.30 and parse_threshold("junk") == 0.30)

    # Tool wiring: the tool attaches a CostGuard and surfaces an approval
    # notice (raised by the client's quote-first gate) instead of executing.
    ks = load("keyword_seo_geo")
    check("GEO metrics registered",
          {"ai_search_volume", "question_keywords", "broad_match"}
          <= set(ks._KEYWORD_METRICS)
          and "domain_overview" in ks._DOMAIN_METRICS)
    tool = object.__new__(ks.KeywordSeoGeoTool)
    tool.create_json_message = lambda d: ("json", d)
    tool.create_text_message = lambda t: ("text", t)
    tool.runtime = types.SimpleNamespace(credentials={"aisa_api_key": "sk-test"})

    notice = {"requires_approval": True, "metric": "keyword_difficulty",
              "estimated_cost": "$0.52", "message": "needs approval"}
    guards = []

    class GatingClient:
        def __init__(self, key):
            pass

        def set_cost_guard(self, guard):
            guards.append(guard)

        def request(self, *a, **kw):
            raise ks.AisaApprovalRequired(dict(notice))

    real_client = ks.AisaClient
    ks.AisaClient = GatingClient
    try:
        out = list(tool._invoke({"metric": "keyword_difficulty",
                                 "keyword": "crm; helpdesk",
                                 "approval_threshold": "0.10"}))
    finally:
        ks.AisaClient = real_client
    check("tool attaches a cost guard with the metric + threshold",
          guards and guards[0].metric == "keyword_difficulty"
          and guards[0].threshold == 0.10)
    check("approval notice surfaced instead of executing",
          out[0][1].get("requires_approval") is True and out[1][0] == "text")

    fp = load("find_prospects")
    check("title splitting", fp._split("CEO, VP Marketing") == ["CEO", "VP Marketing"])
    check("size ranges to Apollo format", fp._size_ranges("11-50, 51-200") == ["11,50", "51,200"])
    check("garbage size ranges dropped", fp._size_ranges("big companies") == [])
    check("bulk enrichment registered", "enrich_bulk" in fp._SEARCH_TYPES)

    av = load("ai_visibility")
    check("claude is a routed LLM engine", "claude" in av._DFS_ENGINES and "claude" in av._SOURCES)
    body = av._dfs_body("chatgpt", "best crm", "gpt-5.6-sol", "US")
    check("chatgpt DFS task: web_search + geo",
          body == [{"user_prompt": "best crm", "model_name": "gpt-5.6-sol",
                    "web_search": True, "web_search_country_iso_code": "US"}])
    body = av._dfs_body("gemini", "q", "gemini-3.8-flash", "US")
    check("gemini: web_search but no country field",
          body[0].get("web_search") is True and "web_search_country_iso_code" not in body[0])
    body = av._dfs_body("perplexity", "q", "sonar-pro", "US")
    check("perplexity: country but no web_search flag",
          body[0].get("web_search_country_iso_code") == "US" and "web_search" not in body[0])

    from utils.aisa_client import AisaApiError as _AE
    ok = av._dfs_result({"tasks": [{"status_code": 20000, "result": [{"a": 1}], "cost": 0.001}]})
    check("DFS envelope unwrapped", ok["result"] == [{"a": 1}])
    try:
        av._dfs_result({"tasks": [{"status_code": 40501, "status_message": "Invalid model_name."}]})
        raise AssertionError("DFS task error not raised")
    except _AE as e:
        check("DFS in-envelope rejection raised (HTTP 200 trap)", e.code == "40501")
    check("first model extracted from models envelope",
          av._first_model({"tasks": [{"result": [{"items": [{"model_name": "sonar"}]}]}]}) == "sonar")
    check("defaults exist for every LLM engine",
          set(av._DEFAULT_MODELS) == set(av._DFS_ENGINES))

    wr = load("web_research")
    wtool = object.__new__(wr.WebResearchTool)

    class FallbackClient:
        def __init__(self):
            self.calls = []

        def tavily_search(self, q):
            raise wr.AisaApiError("502", "tavily upstream down")

        def request(self, method, path, **kw):
            self.calls.append(path)
            return {"results": [{"url": "https://x.com", "title": "t"}]}

    fc = FallbackClient()
    out = wtool._search_with_fallback(fc, "q")
    check("search falls back to firecrawl on upstream failure",
          fc.calls == ["/firecrawl/search"]
          and out.get("provider_fallback", "").startswith("tavily unavailable"))

    class GatedClient(FallbackClient):
        def tavily_search(self, q):
            raise wr.AisaApprovalRequired({"requires_approval": True, "message": "m"})

    try:
        wtool._search_with_fallback(GatedClient(), "q")
        raise AssertionError("approval swallowed by fallback")
    except wr.AisaApprovalRequired:
        check("cost gate is never bypassed via the fallback provider", True)

    ti = load("traffic_intel")
    check("search-intelligence metrics registered",
          {"keyword_competitors", "landing_pages"} <= set(ti._METRICS))
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

    # The snapshot anchor probe is no longer free upstream ($0.52) — it only
    # runs on pre-approved calls; otherwise the free lagged default is used.
    c = StubClient()
    s, e = ti._resolve_window(c, "x.com", "ww", {"approved": True}, span=1)
    check("approved span=1 window anchors to latest via probe",
          (s, e) == ("2026-07", "2026-07"))
    s, e = ti._resolve_window(c, "x.com", "ww", {"approved": True}, span=3)
    check("approved span=3 window covers 3 months", (s, e) == ("2026-05", "2026-07"))
    c = StubClient()
    s, e = ti._resolve_window(c, "x.com", "ww", {}, span=1)
    check("unapproved window skips the paid probe (no snapshot call)",
          c.calls == [] and s == e)
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
        param_names = {p["name"] for p in td.get("parameters", [])}
        check(f"{td['identity']['name']} exposes the cost gate params",
              {"approved", "approval_threshold"} <= param_names)
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


def test_quote_gate():
    """Quote-first price gate: client quotes upstream, guard decides."""
    import utils.aisa_client as m
    from utils.aisa_client import AisaApiError, AisaApprovalRequired
    from utils.gtm_common import CostGuard

    # There is deliberately no static price table anywhere in the plugin —
    # prices change upstream; only live quotes are trusted.
    import utils.gtm_common as gc
    check("no static price table in gtm_common",
          not any("PRICES" in name for name in dir(gc)))

    # CostGuard decision matrix
    g = CostGuard.from_params("keyword_seo_geo", "keyword_difficulty", {})
    check("guard defaults: threshold 0.30, not approved",
          g.threshold == 0.30 and not g.approved)
    check("live price under threshold passes",
          g.decide(0.0087, "/x", "live_quote") is None)
    n = g.decide(0.522, "/similarweb/website-traffic-snapshot", "live_quote")
    check("live price at/above threshold gates",
          n["requires_approval"] is True and n["estimated_cost"] == "$0.52")
    check("notice names endpoint and price source",
          n["endpoint"].endswith("snapshot") and n["price_source"] == "live_quote")
    check("free price never gated even at threshold 0",
          CostGuard("t", "m", 0.0, False).decide(0.0, "/x", "live_quote") is None)
    check("approved bypasses the gate",
          CostGuard.from_params("t", "m", {"approved": True}).decide(9.99, "/x", "live_quote") is None)
    un = CostGuard("t", "m", 0.30, False).decide(None, "/x", "quote_unavailable")
    check("unpriceable call FAILS SAFE (approval required)",
          un["requires_approval"] is True and un["estimated_cost"] == "unknown"
          and un["price_source"] == "quote_unavailable")
    check("approved runs even when unpriceable",
          CostGuard("t", "m", 0.30, True).decide(None, "/x", "quote_unavailable") is None)

    class FakeResp:
        headers = {"Content-Type": "application/json"}

        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    estimate = {"object": "cost_estimate", "estimated_cost_micros_usd": 522000}
    captured = {"payload": estimate}
    original = urllib.request.urlopen

    def fake_urlopen(req, timeout=None):
        captured["mode"] = req.headers.get("X-aisa-cost-mode")
        return FakeResp(captured["payload"])

    urllib.request.urlopen = fake_urlopen
    try:
        c = m.AisaClient("k")
        q = c.quote("GET", "/similarweb/website-traffic-snapshot",
                    params={"domain": "x.com"})
        check("quote sends X-AISA-Cost-Mode: quote", captured["mode"] == "quote")
        check("quote parses estimated micros", q["estimated_cost_micros_usd"] == 522000)
        captured["payload"] = {"ok": True}
        try:
            c.quote("GET", "/x")
            raise AssertionError("non-estimate body accepted as quote")
        except AisaApiError as e:
            check("non-estimate body -> QUOTE_UNAVAILABLE", e.code == "QUOTE_UNAVAILABLE")

        # request() with a guard: gated BEFORE execution
        captured["payload"] = estimate
        c2 = m.AisaClient("k")
        c2.set_cost_guard(CostGuard("traffic_intel", "overview", 0.30, False))
        try:
            c2.request("GET", "/similarweb/website-traffic-snapshot",
                       params={"domain": "x.com"})
            raise AssertionError("expensive call not gated")
        except AisaApprovalRequired as e:
            check("request() raises approval instead of executing",
                  e.notice["estimated_cost"] == "$0.52"
                  and e.notice["price_source"] == "live_quote")

        # approved guard: quote recorded, real call executes
        calls = {"n": 0}

        def counting_urlopen(req, timeout=None):
            calls["n"] += 1
            if req.headers.get("X-aisa-cost-mode") == "quote":
                return FakeResp(estimate)
            return FakeResp({"data": {"month": "2026-08"}})

        urllib.request.urlopen = counting_urlopen
        c3 = m.AisaClient("k")
        c3.set_cost_guard(CostGuard("traffic_intel", "overview", 0.30, True))
        out = c3.request("GET", "/similarweb/website-traffic-snapshot",
                         params={"domain": "x.com"})
        check("approved call quotes first, then executes",
              calls["n"] == 2 and out["data"]["month"] == "2026-08")
        d = c3.cost_disclosure()
        check("cost disclosure records the live quote",
              d["quoted_total_usd"] == 0.522
              and d["quoted_calls"][0]["source"] == "live_quote")

        # quote plane down: FAIL SAFE — every unapproved call is refused as
        # unpriceable (there is no static price table to fall back on)
        def broken_quote_urlopen(req, timeout=None):
            if req.headers.get("X-aisa-cost-mode") == "quote":
                raise ConnectionResetError("quote plane down")
            return FakeResp({"data": "ok"})

        urllib.request.urlopen = broken_quote_urlopen
        c4 = m.AisaClient("k")
        c4.set_cost_guard(CostGuard("social_listening", "reddit", 0.30, False))
        try:
            c4.request("GET", "/reddit/search", params={"query": "x"},
                       retries=0, retry_delay_seconds=0)
            raise AssertionError("unpriceable call was not refused")
        except AisaApprovalRequired as e:
            check("quote-down fails safe: unpriceable call refused",
                  e.notice["price_source"] == "quote_unavailable"
                  and e.notice["estimated_cost"] == "unknown")
        c5 = m.AisaClient("k")
        c5.set_cost_guard(CostGuard("social_listening", "reddit", 0.30, True))
        out = c5.request("GET", "/reddit/search", params={"query": "x"},
                         retries=0, retry_delay_seconds=0)
        check("approved call still executes when quotes are down",
              out == {"data": "ok"})
        d = c5.cost_disclosure()
        check("disclosure marks the unpriced call",
              d["quoted_calls"][0]["source"] == "quote_unavailable"
              and d["quoted_calls"][0]["estimated_cost_usd"] is None
              and d["quoted_total_usd"] == 0)

        # account-plane calls (credential validation) are never quoted
        def account_urlopen(req, timeout=None):
            captured["acct_mode"] = req.headers.get("X-aisa-cost-mode")
            return FakeResp({"available_balance_micros_usd": 1})

        urllib.request.urlopen = account_urlopen
        c6 = m.AisaClient("k")
        c6.set_cost_guard(CostGuard("t", "m", 0.0, False))
        c6.credits_balance()
        check("account-plane calls skip quoting", captured["acct_mode"] is None)
    finally:
        urllib.request.urlopen = original


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
               test_gtm_common, test_tool_helpers, test_quote_gate,
               test_yaml_wiring, test_readme_rules]:
        print(fn.__name__)
        fn()
    print(f"\nAll {PASSED} checks passed.")
