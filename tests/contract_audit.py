"""Contract-drift audit against AIsa's live tool contracts.

Two independent drift surfaces are audited weekly:

1. SCHEMAS — via the AIsa Tool Router (tools.aisa.one/mcp). The router's
   meta-surface was redesigned upstream in Sept 2026: AISA_GET_DETAILS was
   retired in favor of AISA_BATCH_GET_SCHEMA, and per-tool description/price
   fields were dropped from the payload (schema + known_pitfalls remain).
   Compared against:
     a. tests/contracts_baseline.json — the contracts this plugin version was
        built and audited against (hashes over arguments_schema + pitfalls).
     b. The parameters this plugin actually sends per tool (SENT below) —
        sent params must exist in the schema, and required params must all
        be sent. Property names are compared VERBATIM (Apollo schemas use
        'person_titles[]'-style names — do not strip the brackets).

2. PRICES — via the REST gateway's free quote plane (X-AISA-Cost-Mode:
   quote), which the plugin's runtime approval gate depends on. The canary
   fails hard if the quote plane stops answering, and if a live quote
   EXCEEDS the static fallback price (the gate would under-ask whenever
   quotes are down). Verified 2026-09-14: quotes match actual billing.

Exit code 0 = no drift; 1 = drift detected (review, adapt the plugin if
needed, then regenerate the baseline); 2 = audit could not run.

Run:      python3 tests/contract_audit.py            (needs AISA_API_KEY)
Rebase:   python3 tests/contract_audit.py --record   (rewrites the baseline)
CI:       .github/workflows/contract-audit.yml (weekly)

Known accepted deviation (2026-09): the deployed REST gateway rejects
'database' on semrush keyword-overview AND domain-overview although the
schemas document it (verified live 2026-09-14); the plugin deliberately
omits it on both (question-keywords and broad-match-keywords accept it).
"""

import hashlib
import json
import os
import re
import sys
import urllib.request

MCP = "https://tools.aisa.one/mcp"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Params the plugin sends, keyed by the router's tool names.
SENT = {
    "post_tavily_search": {"query"},
    "post_tavily_extract": {"urls"},
    "post_tavily_crawl": {"url", "max_depth"},
    "post_tavily_map": {"url"},
    "similarwebWebsiteTrafficSnapshot": {"domain", "country"},
    "similarwebWebsiteTrafficTrend": {"domain", "country"},
    "similarwebTrafficEngagement": {"domain", "start_date", "end_date", "metrics", "country"},
    "similarwebRanking": {"domain", "start_date", "end_date", "country"},
    "similarwebWebsiteTopGeographies": {"domain"},
    "similarwebDemographics": {"domain", "start_date", "end_date", "granularity", "country"},
    "similarwebSimilarSites": {"domain", "start_date", "end_date", "limit", "country"},
    "similarwebTechnologies": {"domain", "start_date", "end_date", "granularity", "limit", "country"},
    "similarwebPopularPages": {"domain", "start_date", "end_date", "limit", "country"},
    "similarwebKeywordCompetitors": {"domain", "start_date", "end_date", "limit", "country"},
    "similarwebLandingPages": {"domain", "start_date", "end_date", "limit", "country"},
    "get_ahrefs_domain_rating": {"target", "date"},
    "get_ahrefs_site_metrics": {"target", "date"},
    "get_semrush_keyword_overview": {"phrase"},  # database deliberately omitted
    "get_semrush_keyword_difficulty": {"phrase", "database"},
    "get_semrush_question_keywords": {"phrase", "database"},
    "get_semrush_broad_match_keywords": {"phrase", "database"},
    "get_semrush_domain_overview": {"domain"},  # database rejected by gateway (like keyword_overview)
    "get_semrush_domain_organic_keywords": {"domain", "database"},
    "get_semrush_organic_competitors": {"domain", "database"},
    "get_semrush_backlinks_overview": {"target"},
    "post_dataforseo_labs_google_keyword_suggestions_live": set(),   # array body
    "post_dataforseo_keywords_gads_search_volume_live": set(),       # array body
    "post_dataforseo_ai_keyword_volume_live": set(),                 # array body
    "get_twitter_tweet_advanced_search": {"query", "queryType"},
    "get_twitter_user_info": {"userName"},
    "get_reddit_search": {"query", "sort", "trim"},
    "get_reddit_subreddit_search": {"subreddit", "query", "sort"},
    "get_instagram_reels_search": {"query"},
    "get_instagram_profile": {"handle", "trim"},
    "get_pinterest_search": {"query", "trim"},
    "get_youtube_search": {"engine", "q"},
    "post_apollo_mixed_people_api_search": {"person_titles[]", "q_keywords", "person_locations[]",
                                            "organization_num_employees_ranges[]",
                                            "q_organization_domains_list[]", "per_page", "page"},
    "post_apollo_mixed_companies_search": {"q_organization_keyword_tags[]", "organization_locations[]",
                                           "organization_num_employees_ranges[]",
                                           "q_organization_domains_list[]", "per_page", "page"},
    "get_apollo_organizations_enrich": {"domain"},
    "post_apollo_organizations_bulk_enrich": {"domains[]"},
    "post_firecrawl_search": {"query", "limit"},
    "post_waveinflu_similar_creators": {"platform", "seedProfileUrl", "limit", "contentDirection"},
    "post_waveinflu_email_lookup": {"url"},
    "post_oxylabs_ai_search": {"source", "prompt", "query", "parse", "geo_location", "render", "search"},
}

# Quote-plane canaries: (method, REST path, params, body). The runtime price
# gate depends entirely on live quotes (there is deliberately no static price
# table anywhere in this plugin), so the audit fails hard if quoting stops.
# Quotes are free (X-AISA-Cost-Mode: quote) — nothing executes, nothing bills.
QUOTE_CANARIES = [
    ("GET", "/similarweb/website-traffic-snapshot",
     {"domain": "example.com", "country": "us"}, None),
    ("GET", "/semrush/keyword-difficulty",
     {"phrase": "seo tools", "database": "us"}, None),
    ("POST", "/tavily/search", None, {"query": "contract audit canary"}),
]


def call_tool(name, args, rid):
    """One MCP tools/call round-trip; surfaces JSON-RPC error envelopes."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    key = os.environ.get("AISA_API_KEY", "").strip()
    if key:  # discovery requires auth; the schema calls are read-only & free
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(MCP, data=body, headers=headers)
    raw = urllib.request.urlopen(req, timeout=90).read().decode()
    m = re.findall(r"data: (\{.*\})", raw)
    payload = json.loads(m[-1] if m else raw)
    if "error" in payload:
        err = payload["error"]
        raise RuntimeError(
            f"router error {err.get('code')}: {err.get('message')}"
        )
    return json.loads(payload["result"]["content"][0]["text"])


def fetch_live(names):
    live = {}
    for i in range(0, len(names), 20):
        d = call_tool("AISA_BATCH_GET_SCHEMA", {"tools": names[i:i + 20]}, 100 + i)
        live.update(d.get("tools", {}))
    return live


def entry_hashes(contract):
    schema = contract.get("arguments_schema") or {}
    pitfalls = contract.get("known_pitfalls")
    pit_text = json.dumps(pitfalls, sort_keys=True) if pitfalls else ""
    return (
        hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
        hashlib.sha256(pit_text.encode()).hexdigest(),
    )


def record(names):
    live = fetch_live(names)
    baseline = {}
    for name in sorted(names):
        c = live.get(name)
        if not c or not c.get("successful"):
            print(f"CANNOT RECORD: {name} missing/unavailable in live catalog")
            return 2
        schema = c.get("arguments_schema") or {}
        s_hash, p_hash = entry_hashes(c)
        baseline[name] = {
            "schema_sha256": s_hash,
            "pitfalls_sha256": p_hash,
            "properties": sorted((schema.get("properties") or {}).keys()),
            "required": sorted(schema.get("required") or []),
        }
    path = os.path.join(HERE, "contracts_baseline.json")
    with open(path, "w") as f:
        json.dump(baseline, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"Recorded {len(baseline)} contracts to {path}")
    return 0


def audit_quotes():
    """Verify the REST quote plane the runtime price gate depends on."""
    sys.path.insert(0, ROOT)
    from utils.aisa_client import AisaApiError, AisaClient

    key = os.environ.get("AISA_API_KEY", "").strip()
    if not key:
        return ["quote canary: AISA_API_KEY not set — quote plane UNVERIFIED"], []

    hard, info = [], []
    client = AisaClient(key)
    for method, path, params, body in QUOTE_CANARIES:
        try:
            est = client.quote(method, path, params=params, data=body)
            quoted = float(est.get("estimated_cost_micros_usd") or 0) / 1_000_000
            info.append(f"{path}: quote plane serving (${quoted:.4f})")
        except AisaApiError as e:
            hard.append(
                f"quote plane DOWN for {path}: [{e.code}] {e.message} — "
                "the runtime approval gate depends on X-AISA-Cost-Mode: quote "
                "and fails safe (refuses unpriceable calls) while this is broken"
            )
    return hard, info


def main():
    # SENT is the authority on which tools the plugin calls; the baseline
    # must cover exactly that set (regenerate with --record after adding one).
    names = sorted(SENT)

    if "--record" in sys.argv:
        return record(names)

    baseline = json.load(open(os.path.join(HERE, "contracts_baseline.json")))

    try:
        live = fetch_live(names)
    except Exception as e:
        msg = str(e)
        hint = ""
        if "401" in msg:
            hint = " (discovery requires auth — set AISA_API_KEY; the audit calls are read-only and free)"
        elif "unknown tool" in msg.lower():
            hint = (" — the router META-SURFACE changed again (as when "
                    "AISA_GET_DETAILS became AISA_BATCH_GET_SCHEMA); list the "
                    "router's tools and port fetch_live() to the new meta-tool")
        print(f"AUDIT COULD NOT RUN: {msg}{hint}")
        return 2

    drift, hard_fail = [], []
    for name in names:
        c = live.get(name)
        if not c or not c.get("successful"):
            hard_fail.append(f"{name}: MISSING/unavailable in live catalog")
            continue
        base = baseline.get(name)
        if base is None:
            hard_fail.append(f"{name}: not in baseline — run --record after "
                             "adding a tool to SENT")
            continue
        schema = c.get("arguments_schema") or {}
        props = set((schema.get("properties") or {}).keys())
        required = set(schema.get("required") or [])

        s_hash, p_hash = entry_hashes(c)
        if s_hash != base["schema_sha256"]:
            drift.append(f"{name}: arguments_schema CHANGED "
                         f"(props now {sorted(props)}, required {sorted(required)}; "
                         f"baseline props {base['properties']}, required {base['required']})")
        elif p_hash != base["pitfalls_sha256"]:
            drift.append(f"{name}: known_pitfalls prose changed — REVIEW for new "
                         f"window rules / conditional requirements")

        sent = SENT.get(name, set())
        unknown = sent - props
        missing = required - sent if sent else set()
        if unknown:
            hard_fail.append(f"{name}: plugin sends params not in schema: {sorted(unknown)}")
        if missing and name != "get_semrush_keyword_overview":
            hard_fail.append(f"{name}: plugin misses required params: {sorted(missing)}")

    quote_hard, quote_info = audit_quotes()
    hard_fail.extend(quote_hard)

    for line in hard_fail:
        print("FAIL ", line)
    for line in drift:
        print("DRIFT", line)
    for line in quote_info:
        print("info ", line)
    if not hard_fail and not drift:
        print(f"OK — {len(names)} contracts match the baseline and the plugin's "
              "calls; quote plane serving")
        return 0
    print(f"\n{len(hard_fail)} failure(s), {len(drift)} drift notice(s). "
          "Review, adapt tools/ if needed, then regenerate the baseline with "
          "--record.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
