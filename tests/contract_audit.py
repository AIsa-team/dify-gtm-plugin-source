"""Contract-drift audit against AIsa's live tool contracts.

Compares the contracts served by the AIsa Tool Router (tools.aisa.one/mcp,
unauthenticated discovery) against:

  1. tests/contracts_baseline.json — the contracts this plugin version was
     built and audited against. ANY change (schema or description prose —
     window rules and conditional requirements live in prose!) is reported.
  2. The parameters this plugin actually sends per tool (SENT below) — sent
     params must exist in the schema, and required params must all be sent.

Exit code 0 = no drift; 1 = drift detected (review, adapt the plugin if
needed, then regenerate the baseline); 2 = audit could not run.

Run:  python3 tests/contract_audit.py
CI:   .github/workflows/contract-audit.yml (weekly)

Known accepted deviation (2026-09): the deployed gateway rejects
'database' on semrush keyword-overview although the contract documents it;
the plugin deliberately omits it there (SENT reflects that).
"""

import hashlib
import json
import os
import re
import sys
import urllib.request

MCP = "https://tools.aisa.one/mcp"
HERE = os.path.dirname(os.path.abspath(__file__))

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
    "get_ahrefs_domain_rating": {"target", "date"},
    "get_ahrefs_site_metrics": {"target", "date"},
    "get_semrush_keyword_overview": {"phrase"},  # database deliberately omitted
    "get_semrush_keyword_difficulty": {"phrase", "database"},
    "get_semrush_domain_organic_keywords": {"domain", "database"},
    "get_semrush_organic_competitors": {"domain", "database"},
    "get_semrush_backlinks_overview": {"target"},
    "post_dataforseo_labs_google_keyword_suggestions_live": set(),   # array body
    "post_dataforseo_keywords_gads_search_volume_live": set(),       # array body
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
    "post_waveinflu_similar_creators": {"platform", "seedProfileUrl", "limit", "contentDirection"},
    "post_waveinflu_email_lookup": {"url"},
    "post_oxylabs_ai_search": {"source", "prompt", "query", "parse", "geo_location", "render", "search"},
}


def call_tool(name, args, rid):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    key = os.environ.get("AISA_API_KEY", "").strip()
    if key:  # discovery may require auth; AISA_GET_DETAILS is read-only & free
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(MCP, data=body, headers=headers)
    raw = urllib.request.urlopen(req, timeout=90).read().decode()
    m = re.findall(r"data: (\{.*\})", raw)
    return json.loads(json.loads(m[-1] if m else raw)["result"]["content"][0]["text"])


def main():
    baseline = json.load(open(os.path.join(HERE, "contracts_baseline.json")))
    names = sorted(baseline.keys())

    live = {}
    try:
        for i in range(0, len(names), 20):
            d = call_tool("AISA_GET_DETAILS", {"tools": names[i:i + 20]}, 100 + i)
            live.update(d["tools"])
    except Exception as e:
        hint = ""
        if "401" in str(e):
            hint = " (discovery requires auth — set AISA_API_KEY; the audit calls are read-only and free)"
        print(f"AUDIT COULD NOT RUN: {e}{hint}")
        return 2

    drift, hard_fail = [], []
    for name in names:
        c = live.get(name)
        if not c or not c.get("successful"):
            hard_fail.append(f"{name}: MISSING/unavailable in live catalog")
            continue
        schema = c.get("arguments_schema", {})
        props = set(schema.get("properties", {}).keys())
        required = set(schema.get("required", []))
        base = baseline[name]

        args_hash = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        desc_hash = hashlib.sha256((c.get("description") or "").encode()).hexdigest()
        if args_hash != base["args_schema_sha256"]:
            drift.append(f"{name}: arguments_schema CHANGED "
                         f"(props now {sorted(props)}, required {sorted(required)}; "
                         f"baseline props {base['properties']}, required {base['required']})")
        elif desc_hash != base["description_sha256"]:
            drift.append(f"{name}: description prose changed — REVIEW for new "
                         f"window rules / conditional requirements")

        sent = SENT.get(name, set())
        unknown = sent - props
        missing = required - sent if sent else set()
        if unknown:
            hard_fail.append(f"{name}: plugin sends params not in schema: {sorted(unknown)}")
        if missing and name != "get_semrush_keyword_overview":
            hard_fail.append(f"{name}: plugin misses required params: {sorted(missing)}")

    for line in hard_fail:
        print("FAIL ", line)
    for line in drift:
        print("DRIFT", line)
    if not hard_fail and not drift:
        print(f"OK — {len(names)} contracts match the baseline and the plugin's calls")
        return 0
    print(f"\n{len(hard_fail)} failure(s), {len(drift)} drift notice(s). "
          "Review, adapt tools/ if needed, then regenerate contracts_baseline.json.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
