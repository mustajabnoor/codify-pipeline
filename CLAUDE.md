# Codify Pipeline — Project Brief for Claude

Read this file fully at the start of every session. It holds every product and technical decision made so far. If a task conflicts with this file, stop and ask before proceeding.

## 1. What this is

**Codify Pipeline** is an internal lead-generation system for **Codify Labs**, a software development agency based in Lahore, Pakistan (owner: Mustajab Noor, Co-founder / Tech Lead).

An agent runs on a schedule, watches the web for **buying signals** (someone who needs a developer *right now*), turns each signal into a qualified lead with business + contact details, scores it with AI, drafts a personalized outreach message, and stores everything in one database. A dashboard at **https://pipeline.codify-labs.com** lets the team review, approve and track leads from desktop or phone.

**Nothing is ever sent to a lead automatically.** Humans approve every outreach.

### Services Codify Labs sells (used for scoring and messaging)
- MVP / web and mobile app development (incl. Bubble.io — 5+ yrs, Stripe Connect marketplaces)
- App / SaaS development for startups
- AI integration into existing apps and businesses
- Shopify store development and optimization
- Fast, high-converting lead-generation landing pages
- 3D animated business websites
- White-label development for agencies without in-house devs

### Users
- Mustajab only (single user, private tool). Timezone: Asia/Karachi (UTC+5). Dashboard access is limited to emails in the `team_members` table, so another user can be added later without code changes.

## 2. Tech stack (decided — do not change without asking)

| Part | Choice |
|---|---|
| Agent / collectors | **Python 3.12** (managed with **uv**), `httpx`, `pydantic`, `supabase` client, `playwright` (only where a real browser is needed) |
| AI | **Claude API** (Anthropic Python SDK) for extraction, scoring, message drafting |
| Database + auth | **Supabase** (Postgres, Supabase Auth, Row Level Security) |
| Dashboard | **Next.js (App Router) + TypeScript + Tailwind + shadcn/ui**, hosted on **Vercel** at `pipeline.codify-labs.com` |
| Scheduling | **GitHub Actions** cron workflows (one workflow per source) |
| Alerts | **Slack** — daily summary + run alerts via an Incoming Webhook (phase 2); `/run <source>` slash command via a dashboard API route that triggers the source's GitHub workflow (phase 3) |
| Email sending | Not built in. Approved leads are exported/pushed to **Instantly or Smartlead** — phase 4 |

## 3. Repository layout

```
/agent                 Python lead collector
  /sources             one module per source (job_posts.py, funding.py, ...)
  /enrich              contact finding + email verification
  /ai                  Claude prompts: extract, score, draft
  /core                db client, dedupe, models, config, logging
  main.py              CLI: python -m agent run <source> [--dry-run]
  tests/
/dashboard             Next.js app
/supabase
  /migrations          SQL migrations (source of truth for schema)
  seed.sql
/.github/workflows     cron jobs per source + CI (lint, tests)
CLAUDE.md
README.md
.env.example           every required variable, no real values
```

## 4. Lead sources (all 7 are in scope; Upwork is deliberately EXCLUDED)

| # | Source | Buying signal | How to collect | Cadence |
|---|---|---|---|---|
| 1 | **Job postings** | Company hiring a Bubble / Shopify / React / full-stack / mobile developer | RemoteOK JSON API (its RSS is gone), We Work Remotely RSS, Apify job scrapers (LinkedIn Jobs, Indeed), Wellfound | Daily |
| 2 | **Funding news** | Startup just raised pre-seed / seed / Series A | Full-text funding-news RSS (EU-Startups, Tech Funding News, Crunchbase News); Claude extracts company, website, amount, round, founders | Daily |
| 3 | **Social listening** | Public post asking for a developer/agency or describing a broken app | Reddit API (r/forhire, r/startups, r/SaaS, r/Entrepreneur, r/Bubble, r/lovable, r/SideProject), F5Bot alerts, Indie Hackers | Every 4 hours |
| 4 | **Tech-stack detection** | Site on Bubble / Shopify / WordPress that is slow or broken | BuiltWith / Wappalyzer / Store Leads lists + Google PageSpeed Insights API | Weekly batch |
| 5 | **Google Maps** | Local business with no website or a broken/outdated one | Google Places API or Apify Google Maps scraper, by city + category | Weekly |
| 6 | **Product launches** | New product launched, founder likely needs help scaling/fixing | Product Hunt API (GraphQL), BetaList feed | Daily |
| 7 | **Agency partners** | Marketing/design agency with no development service | Clutch + Google Maps searches; check service list on their site | Weekly |

Search keywords, subreddits, cities, categories and job titles live in the `source_configs` table, **not in code**, so they can be edited from the dashboard.

## 5. Pipeline (same for every source)

```
collect → normalize → dedupe → enrich (decision-maker + email) → verify email
        → AI: score fit + explain + draft message → save as status "new"
        → human approves in dashboard → contacted via email / DM / WhatsApp
```

- **Dedupe key:** normalized website domain (lowercase, no `www.`, no path). Leads without a domain (e.g. a Reddit user) dedupe on `source_url`. If a known company appears via a new source, **add a new signal to the existing lead** — never create a duplicate lead.
- **Do-not-contact:** check `do_not_contact` (by email and domain) before inserting or enriching. Skip matches.
- **Enrichment:** Hunter.io (domain search / email finder) or Apollo API. Verify with MillionVerifier (or NeverBounce). Store the verification result; never mark an email valid without a verifier response.
- **Every run** writes a row to `agent_runs` with counts and errors.
- **Every collector supports `--dry-run`** (no DB writes, prints what it would insert as JSON lines; reads Supabase for dedupe when credentials are set).
- **Company domain from text:** collectors whose source gives no website (job boards) take the company's domain from links in the post, accepting only hosts that contain the company name (`company_domain_from_text` in `agent/core/normalize.py`). When unsure it returns none: a wrong domain would merge two companies.
- **Domain-less duplicates are accepted:** the same company reported by two sources without a domain (e.g. a funding round covered by two outlets, one without a company link) becomes two leads; merge or reject them in the dashboard. Matching by company name was considered and rejected (risk of merging different companies).
- **Funding news:** a website counts only if the article itself shows it (`verified_domain` in `agent/sources/funding.py`). Rounds kept: those in `rounds`, plus unnamed rounds up to `unnamed_round_max`. `funding_amount` is stored only for USD; other currencies stay in the signal's metadata. FinSMEs blocks automated requests, so it isn't used.
- **Domain normalization** drops platform hosts (reddit.com, linkedin.com, github.com, producthunt.com, job-board / ATS hosts like greenhouse.io, …) so a link to them never becomes a company domain; customer subdomains on hosting platforms (`acme.myshopify.com`) are kept. List lives in `agent/core/normalize.py`.

## 6. AI steps (Claude API)

Keep prompts in `/agent/ai/prompts/` as versioned files. Request structured JSON output and validate with pydantic.

1. **Extract** — from raw text/page, pull: company name, website, industry, country, size, description, tech stack, funding, people/roles mentioned.
2. **Score** — `fit_score` 1–10 plus `score_reason` (1–2 sentences) and `service_fit` (one or more services from §1). Scoring guide:
   - 9–10: explicit, urgent need matching our services + clear budget signal (funded, hiring, paying business)
   - 7–8: strong signal, likely budget, decision-maker findable
   - 4–6: plausible need, weak budget or unclear contact
   - 1–3: hobby/test project, no budget, or poor fit → auto-status `rejected`
3. **Pain point** — one concrete, observable issue (e.g. "mobile PageSpeed 31/100", "hiring a Bubble dev for 6 weeks", "post says Stripe checkout is broken").
4. **Draft** — subject + body, under 100 words, plain text, first line references the specific signal/pain, one relevant proof point, soft CTA (e.g. "worth a quick look?"). No links in the first email. Also pick `best_channel`: email / linkedin / x / reddit_reply / whatsapp / phone.

Use a cheaper model for extraction and the stronger model for scoring + drafting. Log token usage per run in `agent_runs`.

Implementation (`agent/ai/`):
- Models: extraction `claude-haiku-5-5` (effort low); scoring + drafting `claude-opus-5-5` (effort medium) with server-side refusal fallbacks (`fallbacks: "default"`). Settings per task live in `TASKS` in `agent/ai/client.py`. Always `base_url="https://api.anthropic.com"`.
- AI runs only for candidates that will become **new** leads (after dedupe and do-not-contact), so known companies and posts cost no tokens. Existing leads are not rescored.
- Output is JSON via structured outputs, validated with pydantic (`agent/ai/schemas.py`); an invalid answer is retried once. If any AI step fails for an item, the item is **not saved** and the error goes to `agent_runs.errors`; the next run retries it. A rejected key or unknown model stops the run.
- Real runs require the Anthropic key. Dry runs skip AI when there's no key or with `--no-ai`.
- Proof points: drafts may only cite what is in `agent/ai/prompts/company_profile.md`; keep that file current.
- The sign-off and opt-out line (`SIGN_OFF` in `agent/core/models.py`) are appended by code to every draft and don't count toward the 100 words.
- Sources that need AI to read their items (`needs_ai`, e.g. funding news) extract with their own prompt (`funding_extract_v1`, Haiku) before dedupe, skip article URLs already stored, and cap reads per run (`max_articles`). The generic extract step is then skipped. These sources can't run with `--no-ai`.
- Changing a prompt: add a new version file (`score_v3.md`) and bump the constant in `agent/ai/assess.py`; each signal records the prompt versions in `metadata.ai_prompts`.

## 7. Database (Supabase / Postgres)

Write schema as SQL migrations in `/supabase/migrations` (named `YYYYMMDDHHMMSS_name.sql`). Use `uuid` PKs (`gen_random_uuid()`), `created_at` / `updated_at timestamptz` with an `updated_at` trigger. Enable RLS on every table: signed-in users whose email is in `team_members` can read/write (`public.is_team_member()`); `anon` gets nothing; the agent uses the service-role key. Views use `security_invoker = true`. CI applies all migrations to plain Postgres (`supabase/tests/ci_bootstrap.sql` stubs the Supabase `auth` schema and roles) and runs `supabase/tests/rls_smoke.sql`.

**Enums**
- `lead_source`: job_posting, funding, social, tech_stack, google_maps, product_launch, agency_partner
- `lead_status`: new, reviewing, approved, rejected, contacted, replied, meeting, proposal, won, lost, nurture
- `email_status`: unverified, valid, risky, catch_all, invalid
- `channel`: email, linkedin, x, reddit_reply, whatsapp, phone, other
- `service`: mvp, saas, ai_integration, shopify, landing_page, website_3d, bubble, white_label
- `outreach_status`: draft, approved, sent, replied, bounced
- `reply_category`: interested, not_now, unsubscribe, wrong_person, other
- `run_status`: running, success, partial, failed

**Tables**
- `team_members` — email (PK, lowercase), display_name. Dashboard allow-list; managed from the SQL editor.
- `leads` — company_name, domain (unique where not null), website, industry, country, city, company_size, description, tech_stack text[], funding_amount numeric, funding_round, funding_date, pain_point, service_fit service[], fit_score int (1–10), score_reason, best_channel, status lead_status default 'new', owner (free text, optional — single user for now), first_source lead_source, last_contacted_at, next_follow_up_at, notes
- `signals` — lead_id → leads, source lead_source, source_url (unique), signal_type, title, raw_text, detected_at, metadata jsonb. One lead has many signals.
- `contacts` — lead_id → leads, full_name, role, email, email_status, phone, whatsapp, linkedin_url, x_url, other_url, is_primary bool, found_via
- `outreach` — lead_id, contact_id, channel, subject, draft_body, final_body, status (draft/approved/sent/replied/bounced), sent_at, replied_at, reply_text, reply_category (interested/not_now/unsubscribe/wrong_person/other)
- `activities` — lead_id, type, note, actor, created_at (timeline/audit for each lead)
- `source_configs` — source, name, config jsonb (keywords, subreddits, cities, categories…), schedule text, enabled bool, last_run_at
- `agent_runs` — source (text: lead sources plus non-collector jobs like `fixture`), started_at, finished_at, status run_status, items_seen, leads_new, leads_updated, leads_skipped, errors jsonb, tokens_used, cost_estimate
- `do_not_contact` — email, domain, reason, created_at

**Views** (for the dashboard)
- `v_source_performance` — per `first_source` (all 7 listed, even with 0 leads): leads, approved, contacted, replied, meetings, won, reply rate, win rate. Stages are cumulative (a lead in `meeting` also counts as contacted and replied); reply/win rate are over contacted
- `v_daily_stats` — new leads per day (Asia/Karachi) per source, high-score (≥8) count
- `v_followups_due` — leads where `next_follow_up_at <= now()` and status not in (won, lost, rejected)

## 8. Dashboard (pipeline.codify-labs.com)

Supabase Auth (email magic link), restricted to team accounts. Mobile-first and responsive; installable as a PWA.

Screens:
1. **Today** — KPI cards: new leads today, 8+ score leads, follow-ups due, replies waiting. Short list of top new leads.
2. **Funnel** — Found → Approved → Contacted → Replied → Meeting → Won.
3. **Source performance** — table + chart from `v_source_performance` (the key view: which source produces *meetings and wins*, not just leads).
4. **Leads list** — filter by source, score, service fit, country, status, owner; search; bulk approve/reject; **Export to Excel (.xlsx) and CSV**.
5. **Lead detail** — business info, contacts, all signals (with links), AI score + reason + pain point, editable draft message, Approve / Reject / status change, activity timeline, notes.
6. **Sources** — edit `source_configs` (keywords, cities, subreddits), enable/disable, "Run now".
7. **Agent health** — last run per source, status, leads found, errors, token cost.
8. **Do-not-contact** — add/remove entries.

## 9. Scheduling (GitHub Actions)

One workflow per source in `.github/workflows/`, each runnable manually (`workflow_dispatch`) and on cron (times in UTC; team is UTC+5). Secrets live in GitHub Actions secrets. Add a CI workflow for lint (ruff, eslint) and tests (pytest) on every PR.

## 10. Environment variables (document all in `.env.example`, never commit real values)

```
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=        # agent only, never in the dashboard client
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
ANTHROPIC_API_KEY=
APIFY_TOKEN=
HUNTER_API_KEY=
APOLLO_API_KEY=
MILLIONVERIFIER_API_KEY=
GOOGLE_PAGESPEED_API_KEY=
GOOGLE_PLACES_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=
PRODUCTHUNT_TOKEN=
SLACK_WEBHOOK_URL=                # Slack Incoming Webhook for the alerts channel
```

In Claude Code cloud sessions, these are set in the environment's settings. If a key is missing, the code must fail clearly for that source only, not crash the whole run.

Two dev and prod Supabase projects exist: **pipeline-dev** (Claude Code cloud sessions, dry runs, testing new sources and migrations) and **pipeline-prod** (GitHub Actions secrets, live dashboard). Apply every new migration to dev first, then prod.

**Anthropic key in Claude Code cloud sessions:** the key is stored as `CODIFY_ANTHROPIC_API_KEY` there (so Claude Code itself never picks it up); GitHub Actions uses `ANTHROPIC_API_KEY`. The agent accepts either. Those sessions also set `ANTHROPIC_BASE_URL` for Claude Code's own traffic, which the Anthropic SDK reads by default — the agent must always pass `base_url="https://api.anthropic.com"` explicitly.

## 11. Guardrails (non-negotiable)

- **Never send outreach automatically.** The system only drafts. Sending happens after human approval, through an external tool.
- **Never scrape LinkedIn** directly or log into any site with personal credentials. Use official APIs, RSS, Apify actors, or search APIs.
- Respect each API's rate limits and terms; add backoff and retries.
- Always honor `do_not_contact`; every outreach draft must allow an opt-out line.
- Collect only business contact information relevant to B2B outreach. No sensitive personal data.
- Never commit secrets. Never expose the service-role key to the browser.

## 12. Build roadmap (do phases in order, small PRs)

- **Phase 1 — Foundation:** repo scaffold, Supabase migrations (all tables, enums, views, RLS), `.env.example`, agent core (db client, dedupe, models, run logging, `--dry-run`), CI.
- **Phase 2 — First sources:** Job postings + Funding news end-to-end (collect → enrich → score → draft → save), GitHub Actions crons, Slack daily summary.
  - 2.1 Job postings collector (RemoteOK + WWR), HTTP retry helper (done)
  - 2.2 AI layer: score + draft (+ extract), token/cost logging, `outreach` draft rows (done)
  - 2.3 Enrichment: Hunter + MillionVerifier (blocked: both API keys are rejected; fix them in the cloud environment settings and GitHub secrets)
  - 2.4 Funding news collector (done)
  - 2.5 Cron workflows per source, Slack alerts + daily summary
  - Live runs are allowed once 2.2 is merged; crons come in 2.5. Apify job actors and Wellfound come after 2.5.
- **Phase 3 — Dashboard v1:** auth, Today, Leads list (filters + export), Lead detail (approve/edit), Agent health. Deploy to Vercel on `pipeline.codify-labs.com`.
- **Phase 4 — More sources:** Social listening, Product launches, then Google Maps, Tech-stack, Agency partners.
- **Phase 5 — Outreach:** push approved leads to Instantly/Smartlead, reply import + AI reply categorization, follow-up reminders, source performance view.

## 13. How Claude should work in this repo

- Start each task by restating the goal and the files you'll touch. Use plan mode for anything touching the schema or more than a few files.
- One phase step per branch/PR. Keep PRs small and reviewable.
- Write tests for dedupe, normalization, scoring JSON parsing, and each source's parser (use saved fixture responses, not live calls).
- Prefer simple, readable code over clever abstractions. Type everything (pydantic models in Python, strict TypeScript).
- When something in this file is outdated or a decision needs to change, propose an update to CLAUDE.md in the same PR.
