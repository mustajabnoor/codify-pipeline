-- Enums shared by the agent and the dashboard.
-- Values mirror agent/core/models.py; change both together.

create type public.lead_source as enum (
  'job_posting',
  'funding',
  'social',
  'tech_stack',
  'google_maps',
  'product_launch',
  'agency_partner'
);

create type public.lead_status as enum (
  'new',
  'reviewing',
  'approved',
  'rejected',
  'contacted',
  'replied',
  'meeting',
  'proposal',
  'won',
  'lost',
  'nurture'
);

create type public.email_status as enum (
  'unverified',
  'valid',
  'risky',
  'catch_all',
  'invalid'
);

create type public.channel as enum (
  'email',
  'linkedin',
  'x',
  'reddit_reply',
  'whatsapp',
  'phone',
  'other'
);

create type public.service as enum (
  'mvp',
  'saas',
  'ai_integration',
  'shopify',
  'landing_page',
  'website_3d',
  'bubble',
  'white_label'
);

create type public.outreach_status as enum (
  'draft',
  'approved',
  'sent',
  'replied',
  'bounced'
);

create type public.reply_category as enum (
  'interested',
  'not_now',
  'unsubscribe',
  'wrong_person',
  'other'
);

create type public.run_status as enum (
  'running',
  'success',
  'partial',
  'failed'
);
