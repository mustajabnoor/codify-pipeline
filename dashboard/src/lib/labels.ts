import { Constants, type Database } from "@/lib/database.types";

type Enums = Database["public"]["Enums"];
export type LeadSource = Enums["lead_source"];
export type LeadStatus = Enums["lead_status"];
export type Service = Enums["service"];
export type EmailStatus = Enums["email_status"];

export const LEAD_SOURCES = Constants.public.Enums.lead_source;
export const LEAD_STATUSES = Constants.public.Enums.lead_status;
export const SERVICES = Constants.public.Enums.service;

export const SOURCE_LABELS: Record<LeadSource, string> = {
  job_posting: "Job posting",
  funding: "Funding",
  social: "Social",
  tech_stack: "Tech stack",
  google_maps: "Google Maps",
  product_launch: "Product launch",
  agency_partner: "Agency partner",
};

export const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "New",
  reviewing: "Reviewing",
  approved: "Approved",
  rejected: "Rejected",
  contacted: "Contacted",
  replied: "Replied",
  meeting: "Meeting",
  proposal: "Proposal",
  won: "Won",
  lost: "Lost",
  nurture: "Nurture",
};

export const SERVICE_LABELS: Record<Service, string> = {
  mvp: "MVP",
  saas: "SaaS",
  ai_integration: "AI integration",
  shopify: "Shopify",
  landing_page: "Landing page",
  website_3d: "3D website",
  bubble: "Bubble",
  white_label: "White label",
};

export const EMAIL_STATUS_LABELS: Record<EmailStatus, string> = {
  unverified: "Unverified",
  valid: "Valid",
  risky: "Risky",
  catch_all: "Catch-all",
  invalid: "Invalid",
};

const PKT_DATE = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Karachi",
  day: "2-digit",
  month: "short",
  year: "numeric",
});

/** A date as the team sees it (Asia/Karachi). */
export function formatDate(iso: string | null | undefined): string {
  return iso ? PKT_DATE.format(new Date(iso)) : "";
}
