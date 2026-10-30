-- Starter source configs. Edit them from the dashboard (Sources screen) later.
-- Only job postings and funding are enabled; the rest arrive in Phase 4.

insert into public.source_configs (source, name, config, schedule, enabled) values
(
  'job_posting', 'default',
  '{
    "remoteok": true,
    "rss_feeds": ["https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
                  "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss"],
    "title_keywords": ["bubble", "shopify", "react", "next.js", "full stack", "fullstack",
                       "mobile developer", "mobile engineer", "mobile app", "flutter", "ios",
                       "android", "no-code", "nocode", "webflow", "wordpress", "frontend",
                       "front end", "web developer", "app developer", "mvp"],
    "exclude_keywords": ["senior staff", "unpaid", "equity only"],
    "max_age_days": 30,
    "job_titles": ["bubble developer", "bubble.io developer", "shopify developer",
                   "react developer", "full stack developer", "mobile app developer",
                   "react native developer", "flutter developer", "no-code developer"],
    "apify_actors": []
  }',
  '0 3 * * *', true
),
(
  'funding', 'default',
  '{
    "rss_feeds": [
      "https://www.eu-startups.com/feed/",
      "https://techfundingnews.com/feed/",
      "https://news.crunchbase.com/feed/"
    ],
    "title_keywords": [
      "raise",
      "secure",
      "closes",
      "lands",
      "bags",
      "nabs",
      "snags",
      "grabs",
      "picks up",
      "funding",
      "pre-seed",
      "seed",
      "series a",
      "backed"
    ],
    "exclude_keywords": [
      "series b",
      "series c",
      "series d",
      "series e",
      "series f",
      "ipo",
      "acquire",
      "acquisition",
      "layoffs",
      "fund ii",
      "fund iii",
      "fund iv",
      "second fund",
      "debut fund",
      "new fund",
      "interim close",
      "tracker"
    ],
    "rounds": [
      "pre-seed",
      "seed",
      "series a"
    ],
    "unnamed_round_max": 15000000,
    "max_age_days": 7,
    "max_articles": 40
  }',
  '30 3 * * *', true
),
(
  'social', 'default',
  '{
    "subreddits": ["forhire", "startups", "SaaS", "Entrepreneur", "Bubble", "lovable", "SideProject"],
    "keywords": ["looking for a developer", "need a developer", "hire a developer",
                 "looking for an agency", "bubble developer", "app is broken",
                 "stripe checkout", "need help with my app"],
    "exclude_keywords": ["[for hire]"]
  }',
  '0 */4 * * *', false
),
(
  'tech_stack', 'default',
  '{
    "technologies": ["bubble", "shopify", "wordpress"],
    "max_mobile_pagespeed": 50,
    "countries": ["US", "GB", "CA", "AU", "AE"]
  }',
  '0 4 * * 1', false
),
(
  'google_maps', 'default',
  '{
    "cities": ["Dubai", "London", "Toronto", "Sydney", "New York"],
    "categories": ["dentist", "law firm", "real estate agency", "restaurant", "gym"],
    "signals": ["no_website", "broken_website", "slow_website"]
  }',
  '0 5 * * 2', false
),
(
  'product_launch', 'default',
  '{
    "producthunt_topics": ["saas", "productivity", "no-code", "artificial-intelligence"],
    "betalist": true,
    "min_votes": 20
  }',
  '0 6 * * *', false
),
(
  'agency_partner', 'default',
  '{
    "agency_types": ["marketing agency", "design agency", "branding agency", "seo agency"],
    "cities": ["London", "New York", "Dubai", "Toronto", "Sydney"],
    "exclude_if_services": ["web development", "app development", "software development"]
  }',
  '0 6 * * 3', false
)
on conflict (source, name) do nothing;
