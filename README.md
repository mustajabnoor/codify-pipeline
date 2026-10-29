# Codify Pipeline

Internal lead-generation system for Codify Labs: an agent watches the web for
buying signals, turns them into scored leads with drafted outreach, and stores
them in Supabase. A dashboard (Phase 3) at https://pipeline.codify-labs.com is
used to review and approve leads. **Nothing is ever sent automatically.**

See [CLAUDE.md](CLAUDE.md) for the full product and technical brief.

## Layout

```
agent/        Python collector (python -m agent run <source> [--dry-run])
  core/       config, models, normalize, dedupe, db, runs, pipeline
  sources/    one module per source (Phase 2+), registry.py, fixture.py (dev only)
  enrich/     contact finding + email verification (Phase 2)
  ai/         Claude prompts: extract, score, draft (Phase 2)
  tests/
dashboard/    Next.js app (Phase 3)
supabase/     migrations (schema source of truth), seed.sql, tests/ (CI only)
.github/      CI + per-source cron workflows
```

## Agent

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed by uv.

```bash
uv sync
```

```bash
cp .env.example .env   # fill in what you need; missing keys only fail their source
```

```bash
uv run python -m agent sources
```

```bash
uv run python -m agent run fixture --dry-run
```

`--dry-run` never writes to the database. It prints each would-be insert as a
JSON line on stdout (logs go to stderr). If `SUPABASE_URL` and
`SUPABASE_SERVICE_ROLE_KEY` are set, it reads the real database for dedupe so
it reports the same create / add-signal / skip decisions a real run would.

Exit codes: `0` success or partial (some items failed; see `agent_runs.errors`),
`1` run failed, `2` usage or configuration error.

Checks (same as CI):

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

## Database

Migrations live in `supabase/migrations` and are applied with the Supabase CLI:

```bash
supabase link --project-ref <your-project-ref>
```

```bash
supabase db push
```

Seed the starter source configs once (SQL editor or `psql`) with `supabase/seed.sql`.

Dashboard access is limited to emails in `team_members`. After signing in once
with the magic link, add yourself in the SQL editor:

```sql
insert into public.team_members (email) values ('you@example.com');
```

The agent uses the service-role key, which bypasses RLS. Never put that key in
the dashboard or any `NEXT_PUBLIC_*` variable.
