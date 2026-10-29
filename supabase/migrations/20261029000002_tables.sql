-- Core tables. Emails and domains are stored normalized (lowercase, domain
-- without scheme / www. / path) so equality checks are enough for dedupe.

-- Dashboard allow-list: only these emails pass RLS (see the rls migration).
create table public.team_members (
  email        text primary key check (email = lower(email)),
  display_name text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create table public.leads (
  id                uuid primary key default gen_random_uuid(),
  company_name      text not null,
  domain            text check (
                      domain = lower(domain)
                      and domain !~ '^www\.'
                      and domain !~ '[/:\s]'
                    ),
  website           text,
  industry          text,
  country           text,
  city              text,
  company_size      text,
  description       text,
  tech_stack        text[] not null default '{}',
  funding_amount    numeric(14, 2) check (funding_amount >= 0),
  funding_round     text,
  funding_date      date,
  pain_point        text,
  service_fit       public.service[] not null default '{}',
  fit_score         smallint check (fit_score between 1 and 10),
  score_reason      text,
  best_channel      public.channel,
  status            public.lead_status not null default 'new',
  owner             text,
  first_source      public.lead_source not null,
  last_contacted_at timestamptz,
  next_follow_up_at timestamptz,
  notes             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  -- NULLs are distinct, so leads without a domain never collide.
  constraint leads_domain_key unique (domain)
);

create index leads_status_idx on public.leads (status);
create index leads_first_source_idx on public.leads (first_source);
create index leads_fit_score_idx on public.leads (fit_score desc nulls last);
create index leads_created_at_idx on public.leads (created_at desc);
create index leads_next_follow_up_idx on public.leads (next_follow_up_at)
  where next_follow_up_at is not null;

create table public.signals (
  id          uuid primary key default gen_random_uuid(),
  lead_id     uuid not null references public.leads (id) on delete cascade,
  source      public.lead_source not null,
  source_url  text not null,
  signal_type text not null,
  title       text,
  raw_text    text,
  detected_at timestamptz not null default now(),
  metadata    jsonb not null default '{}',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint signals_source_url_key unique (source_url)
);

create index signals_lead_id_idx on public.signals (lead_id);
create index signals_source_detected_idx on public.signals (source, detected_at desc);

create table public.contacts (
  id           uuid primary key default gen_random_uuid(),
  lead_id      uuid not null references public.leads (id) on delete cascade,
  full_name    text,
  role         text,
  email        text check (email = lower(email)),
  email_status public.email_status not null default 'unverified',
  phone        text,
  whatsapp     text,
  linkedin_url text,
  x_url        text,
  other_url    text,
  is_primary   boolean not null default false,
  found_via    text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint contacts_lead_email_key unique (lead_id, email)
);

create index contacts_lead_id_idx on public.contacts (lead_id);
create index contacts_email_idx on public.contacts (email) where email is not null;
-- At most one primary contact per lead.
create unique index contacts_one_primary_idx on public.contacts (lead_id) where is_primary;

create table public.outreach (
  id             uuid primary key default gen_random_uuid(),
  lead_id        uuid not null references public.leads (id) on delete cascade,
  contact_id     uuid references public.contacts (id) on delete set null,
  channel        public.channel not null,
  subject        text,
  draft_body     text,
  final_body     text,
  status         public.outreach_status not null default 'draft',
  sent_at        timestamptz,
  replied_at     timestamptz,
  reply_text     text,
  reply_category public.reply_category,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index outreach_lead_id_idx on public.outreach (lead_id);
create index outreach_status_idx on public.outreach (status);

create table public.activities (
  id         uuid primary key default gen_random_uuid(),
  lead_id    uuid not null references public.leads (id) on delete cascade,
  type       text not null,
  note       text,
  actor      text not null default 'agent',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index activities_lead_created_idx on public.activities (lead_id, created_at desc);

create table public.source_configs (
  id          uuid primary key default gen_random_uuid(),
  source      public.lead_source not null,
  name        text not null,
  config      jsonb not null default '{}',
  schedule    text,
  enabled     boolean not null default true,
  last_run_at timestamptz,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint source_configs_source_name_key unique (source, name)
);

-- source is text, not lead_source: non-collector jobs (e.g. reply import,
-- the dev "fixture" source) also log runs here.
create table public.agent_runs (
  id            uuid primary key default gen_random_uuid(),
  source        text not null check (source ~ '^[a-z][a-z0-9_]*$'),
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  status        public.run_status not null default 'running',
  items_seen    integer not null default 0,
  leads_new     integer not null default 0,
  leads_updated integer not null default 0,
  leads_skipped integer not null default 0,
  errors        jsonb not null default '[]',
  tokens_used   integer not null default 0,
  cost_estimate numeric(10, 4) not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index agent_runs_source_started_idx on public.agent_runs (source, started_at desc);

create table public.do_not_contact (
  id         uuid primary key default gen_random_uuid(),
  email      text check (email = lower(email)),
  domain     text check (domain = lower(domain) and domain !~ '^www\.' and domain !~ '[/:\s]'),
  reason     text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint do_not_contact_target_check check (email is not null or domain is not null),
  constraint do_not_contact_email_key unique (email),
  constraint do_not_contact_domain_key unique (domain)
);
