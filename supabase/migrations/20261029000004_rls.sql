-- Row Level Security.
-- * Dashboard users sign in with Supabase Auth; only emails listed in
--   public.team_members get access. Add yourself once via the SQL editor:
--     insert into public.team_members (email) values ('you@example.com');
-- * The agent uses the service-role key, which bypasses RLS.
-- * The anon role gets nothing.

create function public.is_team_member()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.team_members tm
    where tm.email = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

revoke execute on function public.is_team_member() from public, anon;
grant execute on function public.is_team_member() to authenticated, service_role;

-- team_members is managed from the SQL editor; members can only read it.
alter table public.team_members enable row level security;
create policy team_members_read on public.team_members
  for select to authenticated
  using ((select public.is_team_member()));

do $$
declare
  t text;
begin
  foreach t in array array[
    'leads', 'signals', 'contacts', 'outreach', 'activities',
    'source_configs', 'agent_runs', 'do_not_contact'
  ]
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format(
      'create policy team_full_access on public.%I
         for all to authenticated
         using ((select public.is_team_member()))
         with check ((select public.is_team_member()))',
      t
    );
  end loop;
end;
$$;

-- Explicit grants (Supabase also grants by default; anon is revoked on purpose).
revoke all on all tables in schema public from anon;
grant select on public.team_members to authenticated;
grant select, insert, update, delete on
  public.leads, public.signals, public.contacts, public.outreach, public.activities,
  public.source_configs, public.agent_runs, public.do_not_contact
  to authenticated;
grant all on all tables in schema public to service_role;
