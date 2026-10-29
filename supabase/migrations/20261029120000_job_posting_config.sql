-- Data-only fix for the job_posting source config seeded by seed.sql.
-- RemoteOK retired its RSS feed (410 Gone); the collector now reads RemoteOK's
-- JSON API ("remoteok": true) and keeps posts whose title matches
-- title_keywords. Fresh databases get this shape from seed.sql directly.
-- Only updates the default row while it still lists the dead feed, so a
-- config edited from the dashboard is never overwritten. job_titles,
-- exclude_keywords and apify_actors are kept as they are.
update public.source_configs
set config = config || '{
  "remoteok": true,
  "rss_feeds": ["https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
                "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss"],
  "title_keywords": ["bubble", "shopify", "react", "next.js", "full stack", "fullstack",
                     "mobile developer", "mobile engineer", "mobile app", "flutter", "ios",
                     "android", "no-code", "nocode", "webflow", "wordpress", "frontend",
                     "front end", "web developer", "app developer", "mvp"],
  "max_age_days": 30
}'::jsonb
where source = 'job_posting'
  and name = 'default'
  and config -> 'rss_feeds' ? 'https://remoteok.com/remote-dev-jobs.rss';
