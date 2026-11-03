-- Phase 4.1: social listening on Reddit (public RSS feeds, agent/sources/social.py).
-- Data only. The Reddit platform becomes available but stays switched off:
-- switch it on from the dashboard's Sources page. F5Bot and Indie Hackers stay
-- unavailable.

update public.source_platforms
set available = true
where key = 'reddit';

-- The default social config gets the keys the collector reads. Keys already in
-- the row win (`defaults || config`), except the seeded "[for hire]" exclude,
-- which the collector now handles itself (it would exclude any post saying
-- "for hire"). The source itself is enabled; the Reddit switch decides whether
-- anything is read.
update public.source_configs
set
  config = '{
    "subreddits": ["forhire", "startups", "SaaS", "Entrepreneur", "Bubble", "lovable", "SideProject"],
    "keywords": ["looking for a developer", "need a developer", "hire a developer",
                 "looking for an agency", "bubble developer", "app is broken",
                 "stripe checkout", "need help with my app"],
    "hiring_subreddits": ["forhire"],
    "hiring_keywords": ["developer", "programmer", "engineer", "app", "website", "web site",
                        "landing page", "bubble", "shopify", "wordpress", "webflow", "react",
                        "next.js", "flutter", "mvp", "saas", "no-code", "nocode", "stripe",
                        "full stack", "fullstack", "frontend", "backend", "ai integration"],
    "exclude_keywords": ["unpaid", "equity only", "rev share", "revenue share", "for exposure"],
    "max_age_days": 3,
    "max_posts": 15,
    "request_delay_seconds": 2
  }'::jsonb || case
    when config -> 'exclude_keywords' = '["[for hire]"]'::jsonb then config - 'exclude_keywords'
    else config
  end,
  schedule = '17 */4 * * *',
  enabled = true
where source = 'social' and name = 'default';
