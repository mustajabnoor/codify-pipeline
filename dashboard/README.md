# Dashboard

Private lead-review app for Codify Labs: Next.js 16 (App Router, Cache
Components) + TypeScript + Tailwind 4 + shadcn/ui, deployed to Vercel at
https://pipeline.codify-labs.com. See CLAUDE.md §8 for the screens.

## Run locally

Needs Node 22.

```bash
cd dashboard && npm install
```

```bash
cp .env.example .env.local   # pipeline-dev URL + anon key
```

```bash
npm run dev
```

Checks (same as CI):

```bash
npm run lint && npm run typecheck && npm test && npm run build
```

## How access works

- Sign-in is by email: a magic link, or the 6-digit code from the same email
  (useful in the installed app, where links open in the browser instead).
- The form never creates accounts (`shouldCreateUser: false`). Add a user once
  in Supabase → Authentication → Users → **Add user**, and add their email to
  `team_members`.
- Signed-in accounts that aren't in `team_members` see "No access". The
  database enforces the same rule with row level security, so the anon key is
  safe in the browser.
- The dashboard never uses the service-role key (CI fails if it appears in `src/`).

## Production

Live at https://pipeline.codify-labs.com (Vercel, owner's account).

- Vercel project: root directory `dashboard`; `main` deploys to production.
- Environment variables: **Production** = pipeline-prod `NEXT_PUBLIC_SUPABASE_URL`
  and `NEXT_PUBLIC_SUPABASE_ANON_KEY`; **Preview** = the pipeline-dev values, so
  PR previews never touch live data. Never add the service-role key.
- Domain: `pipeline.codify-labs.com` (DNS record as shown in Vercel → Domains).
- To give someone access: add them in pipeline-prod Supabase → Authentication →
  Users, then insert their email into `team_members`.

## Supabase Auth settings (dev and prod)

Authentication → URL Configuration:

- **Site URL:** `https://pipeline.codify-labs.com` (dev: `http://localhost:3000`)
- **Redirect URLs:** `https://pipeline.codify-labs.com/**`, `http://localhost:3000/**`

Authentication → Emails → **Magic Link** template (optional but recommended).
It adds the code and a link that works in any browser, not just the one that
asked for it:

```html
<h2>Sign in to Codify Pipeline</h2>
<p><a href="{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=email">Sign in</a></p>
<p>Or enter this code: <strong>{{ .Token }}</strong></p>
```

## Database types

`src/lib/database.types.ts` is generated from `supabase/migrations`. After a
migration changes, regenerate it against any throwaway Postgres with
`supabase/tests/ci_bootstrap.sql` and the migrations applied:

```bash
DATABASE_URL="postgresql://postgres@localhost:5432/postgres?sslmode=disable" npm run gen:types
```

CI fails when the file is out of date.

## UI components

shadcn/ui components live in `src/components/ui` (new-york style, settings in
`components.json`). Add more with `npx shadcn@latest add <name>`.
