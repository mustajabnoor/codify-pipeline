"use server";

import { refresh } from "next/cache";

import { requireMember } from "@/lib/auth";
import { STATUS_LABELS } from "@/lib/labels";
import { OPEN_STATUSES } from "@/lib/leads/filters";
import { createClient } from "@/lib/supabase/server";

export type BulkResult = { changed: number; skipped: number; error?: string };

const MAX_IDS = 200;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Approve or reject leads from the list. Only leads still waiting for a
 * decision (new / reviewing) change; the rest are counted as skipped so a
 * bulk click never moves a lead backwards. Approving also approves the lead's
 * draft. Nothing is ever sent. */
export async function setLeadsStatus(ids: string[], status: "approved" | "rejected"): Promise<BulkResult> {
  const { email } = await requireMember();
  if (status !== "approved" && status !== "rejected") return { changed: 0, skipped: 0, error: "Unknown action." };
  const wanted = [...new Set(ids)].filter((id) => UUID.test(id)).slice(0, MAX_IDS);
  if (!wanted.length) return { changed: 0, skipped: 0 };

  const supabase = await createClient();
  const { data: changed, error } = await supabase
    .from("leads")
    .update({ status })
    .in("id", wanted)
    .in("status", OPEN_STATUSES)
    .select("id");
  if (error) return { changed: 0, skipped: 0, error: `Could not update leads: ${error.message}` };

  const changedIds = changed.map((r) => r.id);
  if (changedIds.length) {
    if (status === "approved") {
      const { error: draftError } = await supabase
        .from("outreach")
        .update({ status: "approved" })
        .in("lead_id", changedIds)
        .eq("status", "draft");
      if (draftError) return { changed: changedIds.length, skipped: 0, error: `Leads updated, drafts not: ${draftError.message}` };
    }
    const { error: logError } = await supabase.from("activities").insert(
      changedIds.map((lead_id) => ({
        lead_id,
        type: "status_changed",
        note: `${STATUS_LABELS[status]} from the leads list`,
        actor: email,
      })),
    );
    if (logError) return { changed: changedIds.length, skipped: 0, error: `Leads updated, timeline not: ${logError.message}` };
  }
  refresh();
  return { changed: changedIds.length, skipped: wanted.length - changedIds.length };
}
