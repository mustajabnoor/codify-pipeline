-- Dashboard views. security_invoker makes them respect the caller's RLS.

-- Per first_source funnel. Stages are cumulative: a lead now in "meeting"
-- also counts as approved, contacted and replied. Leads that ended as lost
-- or nurture count as contacted if they were ever contacted.
create view public.v_source_performance
with (security_invoker = true)
as
with staged as (
  select
    l.first_source,
    l.status,
    (l.last_contacted_at is not null
      or l.status in ('contacted', 'replied', 'meeting', 'proposal', 'won')) as was_contacted,
    (l.status in ('replied', 'meeting', 'proposal', 'won')
      or exists (
        select 1 from public.outreach o
        where o.lead_id = l.id and o.replied_at is not null
      )) as was_replied
  from public.leads l
),
counts as (
  select
    s.source,
    count(st.first_source) as leads,
    count(*) filter (where st.status = 'approved' or st.was_contacted) as approved,
    count(*) filter (where st.was_contacted) as contacted,
    count(*) filter (where st.was_replied) as replied,
    count(*) filter (where st.status in ('meeting', 'proposal', 'won')) as meetings,
    count(*) filter (where st.status = 'won') as won
  from unnest(enum_range(null::public.lead_source)) as s (source)
  left join staged st on st.first_source = s.source
  group by s.source
)
select
  source,
  leads,
  approved,
  contacted,
  replied,
  meetings,
  won,
  round(replied::numeric / nullif(contacted, 0), 3) as reply_rate,
  round(won::numeric / nullif(contacted, 0), 3) as win_rate
from counts;

-- New leads per day (Asia/Karachi) per first_source.
create view public.v_daily_stats
with (security_invoker = true)
as
select
  (l.created_at at time zone 'Asia/Karachi')::date as day,
  l.first_source as source,
  count(*) as new_leads,
  count(*) filter (where l.fit_score >= 8) as high_score_leads
from public.leads l
group by 1, 2;

create view public.v_followups_due
with (security_invoker = true)
as
select
  l.id,
  l.company_name,
  l.domain,
  l.status,
  l.fit_score,
  l.owner,
  l.best_channel,
  l.last_contacted_at,
  l.next_follow_up_at
from public.leads l
where l.next_follow_up_at <= now()
  and l.status not in ('won', 'lost', 'rejected');

revoke all on public.v_source_performance, public.v_daily_stats, public.v_followups_due from anon;
grant select on public.v_source_performance, public.v_daily_stats, public.v_followups_due
  to authenticated, service_role;
