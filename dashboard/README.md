# Dashboard

Next.js (App Router) + TypeScript + Tailwind + shadcn/ui, deployed to Vercel at
https://pipeline.codify-labs.com. See CLAUDE.md §8.

- **Login:** email + password through Supabase Auth. There is no sign-up page;
  accounts are created in Supabase.
- **Access:** only emails listed in `team_members` see any data. RLS
  (`is_team_member()`) enforces this in the database, and the app checks it
  again in `src/lib/dal.ts`.
- **Keys:** the dashboard only ever uses the **public anon key**. The
  service-role key must never be set here.

## Screens (Phase 3)

| Screen | Path | Status |
|---|---|---|
| Today | `/` | 3.1 |
| Agent health | `/health` | 3.1 |
| Leads list | `/leads` | 3.2 |
| Lead detail | `/leads/[id]` | 3.3 |

## Local development

Requires Node 22.

```bash
cd dashboard
```

```bash
npm install
```

Put the **pipeline-dev** values from Supabase → Project Settings → API in
`dashboard/.env.local` (git-ignored):

```
NEXT_PUBLIC_SUPABASE_URL=https://<dev-project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<dev anon / publishable key>
```

```bash
npm run dev
```

Checks (same as CI):

```bash
npm run lint && npm run typecheck && npm test && npm run build
```

Notes for this Next.js version (16):
- `src/proxy.ts` is what older versions called middleware.
- Cache Components are on: request-time data must sit under a `<Suspense>`
  boundary (each route group has a `loading.tsx`).
- Read the guides in `node_modules/next/dist/docs/` before changing routing or
  auth (see `AGENTS.md`).

## Deploy checklist (one time, production)

1. **Create your login** in **pipeline-prod**:
   - Supabase → Authentication → Users → **Add user** → **Create new user**:
     your email, a password, tick **Auto Confirm User**.
   - Then in the SQL Editor:

   ```sql
   insert into public.team_members (email, display_name)
   values ('itsmustajab@gmail.com', 'Mustajab');
   ```

2. **Close sign-ups:** Supabase → Authentication → Sign In / Providers →
   turn **off** "Allow new users to sign up". Accounts are created only from
   the Supabase dashboard.
3. **Vercel:** **Add New → Project** → import `mustajabnoor/codify-pipeline`.
   - **Root Directory:** `dashboard`. The framework is detected as Next.js.
   - **Environment Variables:** `NEXT_PUBLIC_SUPABASE_URL` and
     `NEXT_PUBLIC_SUPABASE_ANON_KEY` with the **pipeline-prod** values.
   - **Deploy.**
4. **Domain:** Vercel → Project → Settings → Domains → add
   `pipeline.codify-labs.com`. Then, at the DNS provider for
   `codify-labs.com`, add the **CNAME** record Vercel shows (name `pipeline`).
5. Open https://pipeline.codify-labs.com, sign in, and on your phone use
   **Add to Home Screen** to install it.

To add a teammate later, repeat step 1 with their email; no code changes are needed.
