"use server";

import { refresh } from "next/cache";

import { requireMember } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";

export type SwitchResult = { ok: boolean; error?: string };

const KEY = /^[a-z][a-z0-9_]*$/;

/** Switch a source platform on or off. Platforms that aren't built yet stay
 * off (the database refuses it too). Applies from the source's next run. */
export async function setPlatformEnabled(key: string, enabled: boolean): Promise<SwitchResult> {
  const { email } = await requireMember();
  if (!KEY.test(key) || typeof enabled !== "boolean") return { ok: false, error: "Unknown platform." };
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("source_platforms")
    .update({ enabled, updated_by: email })
    .eq("key", key)
    .eq("available", true)
    .select("key");
  if (error) return { ok: false, error: `Could not save: ${error.message}` };
  if (!data.length) return { ok: false, error: "This platform isn't available yet." };
  refresh();
  return { ok: true };
}

/** The Claude API switch. Off: runs save leads unscored (no AI, no contact
 * search) and pause sources that need AI to read; back on, the next runs score
 * the waiting leads. */
export async function setAiEnabled(enabled: boolean): Promise<SwitchResult> {
  const { email } = await requireMember();
  if (typeof enabled !== "boolean") return { ok: false, error: "Invalid value." };
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("app_settings")
    .update({ ai_enabled: enabled, updated_by: email })
    .eq("id", true)
    .select("ai_enabled");
  if (error) return { ok: false, error: `Could not save: ${error.message}` };
  if (!data.length) return { ok: false, error: "Settings row missing; apply the latest migration." };
  refresh();
  return { ok: true };
}
