"use server";

import { refresh } from "next/cache";

import { requireMember } from "@/lib/auth";
import { dateInputToIso, LEAD_STATUSES, type LeadStatus, STATUS_LABELS } from "@/lib/labels";
import { UUID } from "@/lib/leads/detail";
import { withSignOff } from "@/lib/outreach";
import { createClient } from "@/lib/supabase/server";

export type ActionResult = { ok: boolean; error?: string };

type Supabase = Awaited<ReturnType<typeof createClient>>;

async function log(supabase: Supabase, leadId: string, actor: string, type: string, note: string) {
  const { error } = await supabase.from("activities").insert({ lead_id: leadId, type, note, actor });
  if (error) throw new Error(`Saved, but the timeline entry failed: ${error.message}`);
}

/** Outreach that has gone out (or come back) is history, not a draft. */
const EDITABLE_OUTREACH = ["draft", "approved"] as const;

async function saveDraftRow(
  supabase: Supabase,
  leadId: string,
  actor: string,
  draft: { outreachId: string; subject: string; body: string },
) {
  if (!UUID.test(draft.outreachId)) throw new Error("Unknown draft.");
  if (!draft.body.trim()) throw new Error("The draft is empty.");
  const { data, error } = await supabase
    .from("outreach")
    .update({ subject: draft.subject.trim() || null, final_body: withSignOff(draft.body) })
    .eq("id", draft.outreachId)
    .eq("lead_id", leadId)
    .in("status", EDITABLE_OUTREACH)
    .select("id");
  if (error) throw new Error(`Could not save the draft: ${error.message}`);
  if (!data.length) throw new Error("This draft can no longer be edited.");
  await log(supabase, leadId, actor, "draft_edited", "Draft edited");
}

async function run(work: (supabase: Supabase, actor: string) => Promise<void>): Promise<ActionResult> {
  const { email } = await requireMember();
  try {
    await work(await createClient(), email);
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "Something went wrong." };
  }
  refresh();
  return { ok: true };
}

/** Save an edited draft. The sign-off is added back by code. */
export async function saveDraft(
  leadId: string,
  draft: { outreachId: string; subject: string; body: string },
): Promise<ActionResult> {
  return run(async (supabase, actor) => {
    if (!UUID.test(leadId)) throw new Error("Unknown lead.");
    await saveDraftRow(supabase, leadId, actor, draft);
  });
}

/** Change a lead's status. Approving saves any unsaved draft edits first and
 * approves the lead's draft; nothing is ever sent from here. */
export async function setStatus(
  leadId: string,
  status: LeadStatus,
  draft?: { outreachId: string; subject: string; body: string },
): Promise<ActionResult> {
  return run(async (supabase, actor) => {
    if (!UUID.test(leadId)) throw new Error("Unknown lead.");
    if (!LEAD_STATUSES.includes(status)) throw new Error("Unknown status.");
    if (draft) await saveDraftRow(supabase, leadId, actor, draft);

    const { data: before, error: readError } = await supabase.from("leads").select("status").eq("id", leadId).single();
    if (readError) throw new Error(`Could not load the lead: ${readError.message}`);
    if (before.status === status) return;

    const { error } = await supabase.from("leads").update({ status }).eq("id", leadId);
    if (error) throw new Error(`Could not change the status: ${error.message}`);
    if (status === "approved") {
      const { error: draftError } = await supabase
        .from("outreach")
        .update({ status: "approved" })
        .eq("lead_id", leadId)
        .eq("status", "draft");
      if (draftError) throw new Error(`Status changed, but the draft wasn't approved: ${draftError.message}`);
    }
    await log(supabase, leadId, actor, "status_changed", `${STATUS_LABELS[before.status]} → ${STATUS_LABELS[status]}`);
  });
}

/** Owner, next follow-up date and notes. */
export async function saveDetails(
  leadId: string,
  details: { owner: string; followUp: string; notes: string },
): Promise<ActionResult> {
  return run(async (supabase, actor) => {
    if (!UUID.test(leadId)) throw new Error("Unknown lead.");
    const followUp = details.followUp ? dateInputToIso(details.followUp) : null;
    if (details.followUp && !followUp) throw new Error("Pick a valid follow-up date.");
    const next = {
      owner: details.owner.trim().slice(0, 100) || null,
      next_follow_up_at: followUp,
      notes: details.notes.trim().slice(0, 10000) || null,
    };

    const { data: before, error: readError } = await supabase
      .from("leads")
      .select("owner, next_follow_up_at, notes")
      .eq("id", leadId)
      .single();
    if (readError) throw new Error(`Could not load the lead: ${readError.message}`);
    const sameTime = (a: string | null, b: string | null) =>
      a === b || (a !== null && b !== null && new Date(a).getTime() === new Date(b).getTime());
    const changed = [
      before.owner !== next.owner && "owner",
      !sameTime(before.next_follow_up_at, next.next_follow_up_at) && "follow-up date",
      before.notes !== next.notes && "notes",
    ].filter((c): c is string => Boolean(c));
    if (!changed.length) return;

    const { error } = await supabase.from("leads").update(next).eq("id", leadId);
    if (error) throw new Error(`Could not save: ${error.message}`);
    await log(supabase, leadId, actor, "details_updated", `Updated ${changed.join(", ")}`);
  });
}
