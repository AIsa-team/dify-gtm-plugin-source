# AIsa Go-to-Market

**Author:** aisa-team
**Version:** 0.1.2
**Type:** tool

Premium go-to-market data for your Dify agents — competitor traffic intelligence, keyword research, social listening, B2B prospecting, creator discovery, and AI answer-engine visibility — all through **one AIsa API key**.

[Documentation in Simplified Chinese](README.zh_Hans.md)

## Why this plugin

Building GTM automation normally means juggling accounts, contracts, and bills for Similarweb, Semrush, Ahrefs, DataForSEO, Apollo, Tavily, Oxylabs, and half a dozen social APIs — an equivalent of **$4,859+/month** in direct vendor costs. The [AIsa Go-to-Market plan](https://aisa.one/solutions/go-to-market) consolidates all of them behind a single key for **$39/month, including $50 of API credit**, and this plugin exposes them to Dify agents and workflows as seven purpose-built tools.

## Tools

| Tool | Backed by | What your agent can do |
|---|---|---|
| **Web Research** | Tavily | Search the live web, extract page content, crawl a site, map its URLs |
| **Traffic Intelligence** | Similarweb + Ahrefs | Domain traffic, engagement, audience geography and demographics, similar sites, tech stack, domain authority |
| **Keyword & SEO** | Semrush + DataForSEO | Keyword volume, difficulty, suggestions, a domain's organic keywords and competitors, backlink profiles |
| **Social Listening** | X, Reddit, Instagram, Pinterest, YouTube | Search brand mentions and conversations, look up public profiles (read-only) |
| **Find Prospects** | Apollo | Search people by title/location/company size, search companies, enrich a company from its domain |
| **Find Creators** | WaveInflu | Discover creators similar to a seed YouTube/TikTok profile, look up creator contact emails |
| **AI Visibility** | Oxylabs | See how ChatGPT, Gemini, Perplexity, or Google AI Mode actually answer a buyer-style question (GEO/AEO) |

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

- **Billing** is usage-based per call through your AIsa account — traffic snapshots/trends are free, most search and social calls cost ~$0.01, Similarweb dated metrics are $0.10, and the most expensive calls are Semrush keyword difficulty ($0.45, up to 20 keywords per call) and organic competitors ($0.36). Failed calls are not charged. When credit runs out, tools return a clear error with a top-up link instead of silently failing.
- **Traffic data lag**: Similarweb monthly metrics trail the current date by about two months. Leave the date parameters empty and the tool picks a valid recent window automatically.
- **Separators**: keyword difficulty accepts up to 20 keywords separated by `;` — search volume accepts up to 100 separated by `,`.
- **Country targeting**: pass two-letter codes or full names ("de", "Germany") — 30+ markets are mapped for localized keyword data.
- **TikTok** content search is not currently available upstream; TikTok *creators* are still discoverable through Find Creators.
- **AI Visibility** queries render a live answer-engine session upstream and can take up to ~2 minutes.
- All tools are **read-only**: nothing is posted, sent, or contacted on your behalf.

## Privacy

Tool inputs (queries, domains, keywords, URLs) are forwarded to AIsa's API to fulfill each request; the plugin itself stores nothing. See [PRIVACY.md](PRIVACY.md) for details.

## Support

- Source repository: [github.com/AIsa-team/dify-gtm-plugin-source](https://github.com/AIsa-team/dify-gtm-plugin-source)
- AIsa documentation: [aisa.one/docs](https://aisa.one/docs)
- Plan and pricing: [aisa.one/solutions/go-to-market](https://aisa.one/solutions/go-to-market)
- Contact: haoyang@aisa.one
