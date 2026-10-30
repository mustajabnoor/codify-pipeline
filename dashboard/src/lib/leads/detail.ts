import "server-only";

import type { QueryData, SupabaseClient } from "@supabase/supabase-js";

import type { Database } from "@/lib/database.types";

type Client = SupabaseClient<Database>;

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function leadQuery(supabase: Client, id: string) {
  return supabase
    .from("leads")
    .select(
      `*,
      contacts(*),
      signals(id, source, source_url, signal_type, title, raw_text, detected_at, metadata),
      outreach(*),
      activities(id, type, note, actor, created_at)`,
    )
    .eq("id", id)
    .order("is_primary", { referencedTable: "contacts", ascending: false })
    .order("detected_at", { referencedTable: "signals", ascending: false })
    .order("created_at", { referencedTable: "outreach", ascending: false })
    .order("created_at", { referencedTable: "activities", ascending: false })
    .maybeSingle();
}

export type LeadDetail = NonNullable<QueryData<ReturnType<typeof leadQuery>>>;

/** One lead with everything attached, or null if it doesn't exist (or isn't visible). */
export async function getLead(supabase: Client, id: string): Promise<LeadDetail | null> {
  if (!UUID.test(id)) return null;
  const { data, error } = await leadQuery(supabase, id);
  if (error) throw new Error(`Could not load the lead: ${error.message}`);
  return data;
}
