-- CI smoke test, run after migrations + seed. Any failure raises an error.

-- 1. RLS is enabled on every public table.
do $$
declare
  missing text;
begin
  select string_agg(c.relname, ', ') into missing
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity;
  if missing is not null then
    raise exception 'RLS disabled on: %', missing;
  end if;
end;
$$;

-- 2. Fixture data (as the superuser, like the service role).
insert into public.team_members (email) values ('owner@example.com');
insert into public.leads (company_name, domain, first_source, status, fit_score, last_contacted_at, next_follow_up_at)
values
  ('Acme', 'acme.com', 'job_posting', 'meeting', 9, now() - interval '3 days', now() - interval '1 hour'),
  ('Beta', 'beta.io', 'funding', 'new', 6, null, null);
insert into public.signals (lead_id, source, source_url, signal_type)
select id, 'job_posting', 'https://example.com/job/1', 'job_post' from public.leads where domain = 'acme.com';

-- 3. Team member sees everything.
set role authenticated;
do $$ begin perform set_config('request.jwt.claims', '{"email": "Owner@Example.com"}', false); end $$;
do $$
begin
  if (select count(*) from public.leads) <> 2 then
    raise exception 'team member should see 2 leads';
  end if;
  if (select meetings from public.v_source_performance where source = 'job_posting') <> 1 then
    raise exception 'v_source_performance meetings wrong';
  end if;
  if (select count(*) from public.v_source_performance) <> 7 then
    raise exception 'v_source_performance should list all 7 sources';
  end if;
  if (select count(*) from public.v_followups_due) <> 1 then
    raise exception 'v_followups_due should have 1 row';
  end if;
  if (select sum(high_score_leads) from public.v_daily_stats) <> 1 then
    raise exception 'v_daily_stats high_score_leads wrong';
  end if;
end;
$$;
update public.leads set notes = 'checked' where domain = 'beta.io';
reset role;

-- 4. Signed-in stranger sees nothing and cannot write.
set role authenticated;
do $$ begin perform set_config('request.jwt.claims', '{"email": "stranger@example.com"}', false); end $$;
do $$
begin
  if (select count(*) from public.leads) <> 0 then
    raise exception 'non-member must not see leads';
  end if;
  if (select coalesce(sum(leads), 0) from public.v_source_performance) <> 0 then
    raise exception 'non-member must not see view data';
  end if;
  begin
    insert into public.leads (company_name, first_source) values ('Evil', 'social');
    raise exception 'non-member insert should have failed';
  exception when insufficient_privilege then
    null;
  end;
end;
$$;
reset role;

-- 5. anon has no table access at all.
set role anon;
do $$
begin
  perform 1 from public.leads;
  raise exception 'anon should not read leads';
exception when insufficient_privilege then
  null;
end;
$$;
reset role;

-- 6. updated_at trigger fired on the update above.
do $$
begin
  if (select updated_at <= created_at from public.leads where domain = 'beta.io') then
    raise exception 'updated_at trigger did not fire';
  end if;
end;
$$;

select 'rls smoke test passed' as result;
