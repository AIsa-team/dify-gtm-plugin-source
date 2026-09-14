# AIsa Go-to-Market

**Author:** aisa-team
**Version:** 0.2.0
**Type:** tool

Premium go-to-market data for your Dify agents — competitor traffic intelligence, keyword research, social listening, B2B prospecting, creator discovery, and AI answer-engine visibility — all through **one AIsa API key**.

[Documentation in Simplified Chinese](README.zh_Hans.md)

## Why this plugin

Building GTM automation normally means juggling accounts, contracts, and bills for Similarweb, Semrush, Ahrefs, DataForSEO, Apollo, Tavily, Oxylabs, and half a dozen social APIs — an equivalent of **$4,859+/month** in direct vendor costs. The [AIsa Go-to-Market plan](https://aisa.one/solutions/go-to-market) consolidates all of them behind a single key for **$39/month, including $50 of API credit**, and this plugin exposes them to Dify agents and workflows as seven purpose-built tools.

## Tools

| Tool | Backed by | What your agent can do |
|---|---|---|
| **Web Research** | Tavily + Firecrawl | Search the live web (with automatic provider fallback), extract page content, crawl a site, map its URLs |
| **Traffic Intelligence** | Similarweb + Ahrefs | Domain traffic, engagement, audience geography and demographics, similar sites, tech stack, search keyword competitors, search landing pages, domain authority |
| **Keyword, SEO & GEO** | Semrush + DataForSEO | Keyword volume, difficulty, suggestions, question keywords, broad-match ideas, AI-prompt volume (GEO), a domain's organic keywords, competitors, overview and backlink profiles |
| **Social Listening** | X, Reddit, Instagram, Pinterest, YouTube | Search brand mentions and conversations, look up public profiles (read-only) |
| **Find Prospects** | Apollo | Search people by title/location/company size, search companies, enrich a company from its domain — or up to 10 companies in one bulk call |
| **Find Creators** | WaveInflu | Discover creators similar to a seed YouTube/TikTok profile, look up creator contact emails |
| **AI Visibility** | Oxylabs + DataForSEO | See how ChatGPT, Gemini, Perplexity, Claude, Google AI Mode, or classic Google actually answer a buyer-style question (GEO/AEO) — six engines |

### Example prompts

- "Tear down linear.app — how big are they and who do they compete with?"
- "What keywords should we target for an AI meeting-notes product in Germany?"
- "What are people saying about our brand on X and Reddit this week?"
- "Build a list of Heads of Growth at 11-50 person SaaS companies in the US."
- "Find YouTube creators similar to this channel and get contact emails for the top 3."
- "When someone asks ChatGPT for the best CRM for startups, do we come up?"

## Setup

1. **Get an AIsa API key** — subscribe to the [Go-to-Market plan](https://aisa.one/solutions/go-to-market) ($39/month with $50 API credit included; usage-based beyond that).
2. **Install this plugin** in Dify, open its provider settings, and paste the key. Validation is free — the plugin checks the key against AIsa's account-balance endpoint without spending credit.
3. **Attach the tools** to your Agent app or workflow. All seven tools share the one credential.

### Connection requirements

The plugin makes outbound HTTPS (port 443) requests to **`api.aisa.one` only** — no other hosts, no inbound connections, no telemetry. It runs in Dify's standard plugin runtime with default permissions (no storage, model, or endpoint permissions required).

## Usage notes

- **Quote-first billing**: before executing ANY call, the plugin fetches a free upstream price quote for that exact request (AIsa's `X-AISA-Cost-Mode: quote` header — nothing runs, nothing is charged). Calls quoted at or above your approval threshold (default $0.30, configurable per call) return a structured approval request instead of executing; retry with `approved=true` after the user consents. Successful responses include the quoted cost. Failed calls are not charged. When credit runs out, tools return a clear error with a top-up link instead of silently failing.
- **No static price list**: upstream prices change, so this plugin publishes none — the live quote (shown in every approval request and response) is always the authority. If the quote service itself is ever unavailable, the gate fails safe: unpriceable calls are refused until explicitly approved.
- **Traffic data lag**: Similarweb monthly metrics trail the current date by about two months. Leave the date parameters empty and the tool picks a valid recent window automatically (a stale window self-heals by advancing one month and retrying).
- **Separators**: keyword difficulty accepts up to 20 keywords separated by `;` — search volume accepts up to 100 separated by `,`.
- **Country targeting**: pass two-letter codes or full names ("de", "Germany") — 30+ markets are mapped for localized keyword data.
- **TikTok** content search is not currently available upstream; TikTok *creators* are still discoverable through Find Creators.
- **AI Visibility** covers six engines across two providers; LLM-engine sessions can take up to ~2 minutes.
- All tools are **read-only**: nothing is posted, sent, or contacted on your behalf.

## Privacy

Tool inputs (queries, domains, keywords, URLs) are forwarded to AIsa's API to fulfill each request; the plugin itself stores nothing. Requests identify the plugin by name and version via the standard `User-Agent` header so AIsa can support and improve the integration — no other client information is sent. See [PRIVACY.md](PRIVACY.md) for details.

## Support

- Source repository: [github.com/AIsa-team/dify-gtm-plugin-source](https://github.com/AIsa-team/dify-gtm-plugin-source)
- AIsa documentation: [aisa.one/docs](https://aisa.one/docs)
- Plan and pricing: [aisa.one/solutions/go-to-market](https://aisa.one/solutions/go-to-market)
- Contact: haoyang@aisa.one
