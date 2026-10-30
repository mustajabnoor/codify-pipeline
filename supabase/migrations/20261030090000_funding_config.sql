-- Data-only fix for the funding source config seeded by seed.sql, which had
-- no feeds and used a "keywords" key the collector doesn't read. The collector
-- (agent/sources/funding.py) reads title_keywords, exclude_keywords, rounds,
-- unnamed_round_max, max_age_days and max_articles. Fresh databases get this
-- shape from seed.sql directly. Only the default row is updated, and only
-- while its rss_feeds is still empty, so a config edited from the dashboard
-- is never overwritten.
update public.source_configs
set config = (config - 'keywords') || '{
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
}'::jsonb
where source = 'funding'
  and name = 'default'
  and config -> 'rss_feeds' = '[]'::jsonb;
