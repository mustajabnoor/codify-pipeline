// Types for the Supabase schema in supabase/migrations (the source of truth).
// Hand-written; enums are checked against the migrations by
// src/lib/database.types.test.ts, so a schema change that isn't mirrored here
// fails CI.

export const ENUMS = {
  lead_source: [
    "job_posting",
    "funding",
    "social",
    "tech_stack",
    "google_maps",
    "product_launch",
    "agency_partner",
  ],
  lead_status: [
    "new",
    "reviewing",
    "approved",
    "rejected",
    "contacted",
    "replied",
    "meeting",
    "proposal",
    "won",
    "lost",
    "nurture",
  ],
  email_status: ["unverified", "valid", "risky", "catch_all", "invalid"],
  channel: ["email", "linkedin", "x", "reddit_reply", "whatsapp", "phone", "other"],
  service: [
    "mvp",
    "saas",
    "ai_integration",
    "shopify",
    "landing_page",
    "website_3d",
    "bubble",
    "white_label",
  ],
  outreach_status: ["draft", "approved", "sent", "replied", "bounced"],
  reply_category: ["interested", "not_now", "unsubscribe", "wrong_person", "other"],
  run_status: ["running", "success", "partial", "failed"],
} as const;

type Enum<K extends keyof typeof ENUMS> = (typeof ENUMS)[K][number];

export type LeadSource = Enum<"lead_source">;
export type LeadStatus = Enum<"lead_status">;
export type EmailStatus = Enum<"email_status">;
export type Channel = Enum<"channel">;
export type Service = Enum<"service">;
export type OutreachStatus = Enum<"outreach_status">;
export type ReplyCategory = Enum<"reply_category">;
export type RunStatus = Enum<"run_status">;

type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[];

type Timestamps = { created_at: string; updated_at: string };

export type TeamMember = Timestamps & { email: string; display_name: string | null };

export type Lead = Timestamps & {
  id: string;
  company_name: string;
  domain: string | null;
  website: string | null;
  industry: string | null;
  country: string | null;
  city: string | null;
  company_size: string | null;
  description: string | null;
  tech_stack: string[];
  funding_amount: number | null;
  funding_round: string | null;
  funding_date: string | null;
  pain_point: string | null;
  service_fit: Service[];
  fit_score: number | null;
  score_reason: string | null;
  best_channel: Channel | null;
  status: LeadStatus;
  owner: string | null;
  first_source: LeadSource;
  last_contacted_at: string | null;
  next_follow_up_at: string | null;
  notes: string | null;
};

export type Signal = Timestamps & {
  id: string;
  lead_id: string;
  source: LeadSource;
  source_url: string;
  signal_type: string;
  title: string | null;
  raw_text: string | null;
  detected_at: string;
  metadata: Json;
};

export type Contact = Timestamps & {
  id: string;
  lead_id: string;
  full_name: string | null;
  role: string | null;
  email: string | null;
  email_status: EmailStatus;
  phone: string | null;
  whatsapp: string | null;
  linkedin_url: string | null;
  x_url: string | null;
  other_url: string | null;
  is_primary: boolean;
  found_via: string | null;
};

export type Outreach = Timestamps & {
  id: string;
  lead_id: string;
  contact_id: string | null;
  channel: Channel;
  subject: string | null;
  draft_body: string | null;
  final_body: string | null;
  status: OutreachStatus;
  sent_at: string | null;
  replied_at: string | null;
  reply_text: string | null;
  reply_category: ReplyCategory | null;
};

export type Activity = Timestamps & {
  id: string;
  lead_id: string;
  type: string;
  note: string | null;
  actor: string;
};

export type SourceConfig = Timestamps & {
  id: string;
  source: LeadSource;
  name: string;
  config: Json;
  schedule: string | null;
  enabled: boolean;
  last_run_at: string | null;
};

export type RunError = { message: string; context?: Record<string, Json>; at?: string };

export type AgentRun = Timestamps & {
  id: string;
  source: string;
  started_at: string;
  finished_at: string | null;
  status: RunStatus;
  items_seen: number;
  leads_new: number;
  leads_updated: number;
  leads_skipped: number;
  errors: RunError[];
  tokens_used: number;
  cost_estimate: number;
};

export type DoNotContact = Timestamps & {
  id: string;
  email: string | null;
  domain: string | null;
  reason: string | null;
};

export type FollowupDue = Pick<
  Lead,
  | "id"
  | "company_name"
  | "domain"
  | "status"
  | "fit_score"
  | "owner"
  | "best_channel"
  | "last_contacted_at"
  | "next_follow_up_at"
>;

// Shape supabase-js expects for a typed client.
type Relationship = {
  foreignKeyName: string;
  columns: string[];
  isOneToOne: boolean;
  referencedRelation: string;
  referencedColumns: string[];
};

type Table<Row, Relationships extends Relationship[] = []> = {
  Row: Row;
  Insert: Partial<Row>;
  Update: Partial<Row>;
  Relationships: Relationships;
};

// Tables with lead_id -> leads.id (Postgres names the FK <table>_lead_id_fkey).
type BelongsToLead<T extends string> = [
  {
    foreignKeyName: `${T}_lead_id_fkey`;
    columns: ["lead_id"];
    isOneToOne: false;
    referencedRelation: "leads";
    referencedColumns: ["id"];
  },
];

export type Database = {
  public: {
    Tables: {
      team_members: Table<TeamMember>;
      leads: Table<Lead>;
      signals: Table<Signal, BelongsToLead<"signals">>;
      contacts: Table<Contact, BelongsToLead<"contacts">>;
      outreach: Table<Outreach, BelongsToLead<"outreach">>;
      activities: Table<Activity, BelongsToLead<"activities">>;
      source_configs: Table<SourceConfig>;
      agent_runs: Table<AgentRun>;
      do_not_contact: Table<DoNotContact>;
    };
    Views: {
      v_followups_due: { Row: FollowupDue; Relationships: [] };
    };
    Functions: { is_team_member: { Args: Record<string, never>; Returns: boolean } };
    Enums: { [K in keyof typeof ENUMS]: (typeof ENUMS)[K][number] };
    CompositeTypes: Record<string, never>;
  };
};
