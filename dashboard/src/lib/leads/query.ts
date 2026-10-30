import "server-only";

import type { QueryData, SupabaseClient } from "@supabase/supabase-js";

import type { Database } from "@/lib/database.types";

import { type LeadFilters, PAGE_SIZE } from "./filters";

type Client = SupabaseClient<Database>;

const LEAD_COLUMNS = `
  id, company_name, domain, website, fit_score, status, first_source, service_fit,
  country, city, industry, company_size, owner, pain_point, score_reason,
  funding_round, funding_amount, created_at,
  contacts(full_name, role, email, email_status, linkedin_url, is_primary),
  outreach(subject, draft_body, final_body, status, created_at)
`;

function baseQuery(supabase: Client, filters: LeadFilters) {
  let query = supabase.from("leads").select(LEAD_COLUMNS, { count: "exact" });
  if (filters.source) query = query.eq("first_source", filters.source);
  if (filters.status.length) query = query.in("status", filters.status);
  if (filters.service) query = query.contains("service_fit", [filters.service]);
  if (filters.country) query = query.eq("country", filters.country);
  if (filters.owner) query = query.eq("owner", filters.owner);
  if (filters.minScore) query = query.gte("fit_score", filters.minScore);
  // filters.q is cleaned of PostgREST syntax in parseFilters.
  if (filters.q) query = query.or(`company_name.ilike."%${filters.q}%",domain.ilike."%${filters.q}%"`);
  if (filters.sort === "newest") return query.order("created_at", { ascending: false });
  return query
    .order("fit_score", { ascending: false, nullsFirst: false })
    .order("created_at", { ascending: false });
}

type LeadQuery = ReturnType<typeof baseQuery>;
export type LeadRow = QueryData<LeadQuery>[number];

/** One page of the Leads list, with the total matching count. */
export async function listLeads(supabase: Client, filters: LeadFilters) {
  const from = (filters.page - 1) * PAGE_SIZE;
  const { data, count, error } = await baseQuery(supabase, filters).range(from, from + PAGE_SIZE - 1);
  if (error) throw new Error(`Could not load leads: ${error.message}`);
  return { rows: data, total: count ?? 0 };
}

export const EXPORT_MAX_ROWS = 5000;
const BATCH = 1000; // Supabase returns at most 1,000 rows per request

/** Every lead matching the filters (up to EXPORT_MAX_ROWS), for export. */
export async function allLeads(supabase: Client, filters: LeadFilters) {
  const rows: LeadRow[] = [];
  let total = 0;
  for (let from = 0; from < EXPORT_MAX_ROWS; from += BATCH) {
    const to = Math.min(from + BATCH, EXPORT_MAX_ROWS) - 1;
    const { data, count, error } = await baseQuery(supabase, filters).range(from, to);
    if (error) throw new Error(`Could not load leads: ${error.message}`);
    rows.push(...data);
    total = count ?? rows.length;
    if (data.length < to - from + 1) break;
  }
  return { rows, total };
}

/** Values for the country and owner filter menus. */
export async function filterOptions(supabase: Client) {
  const { data, error } = await supabase.from("leads").select("country, owner").limit(5000);
  if (error) throw new Error(`Could not load filter options: ${error.message}`);
  const distinct = (values: (string | null)[]) =>
    [...new Set(values.filter((v): v is string => Boolean(v)))].sort((a, b) => a.localeCompare(b));
  return { countries: distinct(data.map((r) => r.country)), owners: distinct(data.map((r) => r.owner)) };
}

/** The contact a draft goes to: primary, else the first with an email. */
export function primaryContact(row: Pick<LeadRow, "contacts">) {
  return row.contacts.find((c) => c.is_primary) ?? row.contacts.find((c) => c.email) ?? null;
}

/** The lead's latest outreach draft, if any. */
export function latestDraft(row: Pick<LeadRow, "outreach">) {
  return [...row.outreach].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
}
