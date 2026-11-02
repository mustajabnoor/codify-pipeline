-- Source platforms: the boards, feeds and APIs a source collects from
-- (RemoteOK and We Work Remotely for job postings, EU-Startups for funding
-- news, ...). Each can be switched on or off from the dashboard's Sources page;
-- platforms that aren't built yet are listed with available = false and can't
-- be switched on. The agent records each platform's last run here.
--
-- Also: app_settings (one row) with the Claude API switch, and the platform a
-- lead / signal came from.

create table public.source_platforms (
  key                text primary key check (key ~ '^[a-z][a-z0-9_]*$'),
  source             public.lead_source not null,
  name               text not null,
  -- Built and collectable. Flipped by the migration that ships a platform.
  available          boolean not null default false,
  enabled            boolean not null default false,
  -- Needs Claude to read its items (funding news); paused while AI is off.
  needs_ai           boolean not null default false,
  sort_order         smallint not null default 0,
  last_run_at        timestamptz,
  last_run_status    public.run_status,
  last_run_items     integer,
  last_run_leads_new integer,
  last_run_error     text,
  updated_by         text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint source_platforms_enabled_needs_available check (available or not enabled)
);

insert into public.source_platforms (key, source, name, available, enabled, needs_ai, sort_order) values
  ('remoteok',             'job_posting',    'RemoteOK',               true,  true,  false, 10),
  ('weworkremotely',       'job_posting',    'We Work Remotely',       true,  true,  false, 20),
  ('linkedin_jobs',        'job_posting',    'LinkedIn Jobs (Apify)',  false, false, false, 30),
  ('indeed',               'job_posting',    'Indeed (Apify)',         false, false, false, 40),
  ('wellfound',            'job_posting',    'Wellfound',              false, false, false, 50),
  ('eu_startups',          'funding',        'EU-Startups',            true,  true,  true,  10),
  ('tech_funding_news',    'funding',        'Tech Funding News',      true,  true,  true,  20),
  ('crunchbase_news',      'funding',        'Crunchbase News',        true,  true,  true,  30),
  ('reddit',               'social',         'Reddit',                 false, false, false, 10),
  ('f5bot',                'social',         'F5Bot',                  false, false, false, 20),
  ('indie_hackers',        'social',         'Indie Hackers',          false, false, false, 30),
  ('builtwith',            'tech_stack',     'BuiltWith',              false, false, false, 10),
  ('wappalyzer',           'tech_stack',     'Wappalyzer',             false, false, false, 20),
  ('store_leads',          'tech_stack',     'Store Leads',            false, false, false, 30),
  ('google_maps',          'google_maps',    'Google Maps',            false, false, false, 10),
  ('product_hunt',         'product_launch', 'Product Hunt',           false, false, false, 10),
  ('betalist',             'product_launch', 'BetaList',               false, false, false, 20),
  ('clutch',               'agency_partner', 'Clutch',                 false, false, false, 10),
  ('google_maps_agencies', 'agency_partner', 'Google Maps (agencies)', false, false, false, 20);

-- RemoteOK used to be switched by a "remoteok" flag in the job_posting config;
-- carry its value over, then drop the flag (the platform switch replaces it).
update public.source_platforms
set enabled = coalesce(
  (select bool_or(coalesce((c.config ->> 'remoteok')::boolean, true))
   from public.source_configs c
   where c.source = 'job_posting' and c.config ? 'remoteok'),
  true
)
where key = 'remoteok';

update public.source_configs
set config = config - 'remoteok'
where source = 'job_posting' and config ? 'remoteok';

-- One row: settings that apply to every run.
create table public.app_settings (
  id         boolean primary key default true check (id),
  -- Off: runs still collect, but leads are saved without score, draft or
  -- contact; sources that need AI to read (funding news) are skipped. Once
  -- back on, the next run of each source scores its unscored new leads.
  ai_enabled boolean not null default true,
  updated_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

insert into public.app_settings default values;

-- Where each signal / lead came from.
alter table public.signals
  add column platform text references public.source_platforms (key) on update cascade;
alter table public.leads
  add column source_platform text references public.source_platforms (key) on update cascade;

create index leads_source_platform_idx on public.leads (source_platform);
-- Finds unscored new leads to score once AI is back on.
create index leads_unscored_idx on public.leads (first_source, created_at)
  where fit_score is null and status = 'new';

-- Backfill from the signal URL's host.
update public.signals s
set platform = p.key
from (values
  ('remoteok.com', 'remoteok'),
  ('weworkremotely.com', 'weworkremotely'),
  ('eu-startups.com', 'eu_startups'),
  ('techfundingnews.com', 'tech_funding_news'),
  ('news.crunchbase.com', 'crunchbase_news')
) as p (host, key)
where s.platform is null
  and (
    regexp_replace(lower(substring(s.source_url from '^https?://([^/:?#]+)')), '^www\.', '') = p.host
    or lower(substring(s.source_url from '^https?://([^/:?#]+)')) like '%.' || p.host
  );

-- A lead's platform is that of its first signal from its first source.
update public.leads l
set source_platform = first_signal.platform
from (
  select distinct on (s.lead_id) s.lead_id, s.platform
  from public.signals s
  join public.leads l2 on l2.id = s.lead_id and l2.first_source = s.source
  order by s.lead_id, s.detected_at, s.created_at
) as first_signal
where first_signal.lead_id = l.id
  and l.source_platform is null
  and first_signal.platform is not null;

-- updated_at triggers.
create trigger set_updated_at before update on public.source_platforms
  for each row execute function public.set_updated_at();
create trigger set_updated_at before update on public.app_settings
  for each row execute function public.set_updated_at();

-- RLS: team members read both tables and may only flip the switches (column
-- grants below); the agent (service role) writes the run fields.
alter table public.source_platforms enable row level security;
alter table public.app_settings enable row level security;

create policy team_read on public.source_platforms
  for select to authenticated
  using ((select public.is_team_member()));
create policy team_update on public.source_platforms
  for update to authenticated
  using ((select public.is_team_member()))
  with check ((select public.is_team_member()));

create policy team_read on public.app_settings
  for select to authenticated
  using ((select public.is_team_member()));
create policy team_update on public.app_settings
  for update to authenticated
  using ((select public.is_team_member()))
  with check ((select public.is_team_member()));

revoke all on public.source_platforms, public.app_settings from anon, authenticated;
grant select on public.source_platforms, public.app_settings to authenticated;
grant update (enabled, updated_by) on public.source_platforms to authenticated;
grant update (ai_enabled, updated_by) on public.app_settings to authenticated;
grant all on public.source_platforms, public.app_settings to service_role;
