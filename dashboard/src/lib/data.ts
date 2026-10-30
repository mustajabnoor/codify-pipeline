import "server-only";

import { requireMember } from "@/lib/dal";
import type { AgentRun, Lead, Signal } from "@/lib/database.types";
import { startOfTeamDay } from "@/lib/time";

export type LeadSummary = Pick<
  Lead,
  | "id"
  | "company_name"
  | "domain"
  | "fit_score"
  | "status"
  | "first_source"
  | "pain_point"
  | "funding_round"
  | "created_at"
> & { signals: Pick<Signal, "source_url" | "title" | "detected_at">[] };

const LEAD_SUMMARY =
  "id, company_name, domain, fit_score, status, first_source, pain_point, funding_round, created_at, signals(source_url, title, detected_at)";

function rows<T>(result: { data: T[] | null; error: { message: string } | null }): T[] {
  if (result.error) throw new Error(result.error.message);
  return result.data ?? [];
}

function count(result: { count: number | null; error: { message: string } | null }): number {
  if (result.error) throw new Error(result.error.message);
  return result.count ?? 0;
}

export type TodayData = {
  newToday: number;
  highScoreToday: number;
  followupsDue: number;
  repliesWaiting: number;
  topToday: LeadSummary[];
  /** Shown when nothing came in today yet (runs start at 08:00 Karachi). */
  recent: LeadSummary[];
};

export async function getToday(): Promise<TodayData> {
  const { supabase } = await requireMember();
  // Read the clock only after the session check: the page is per-request.
  const now = new Date();
  const dayStart = startOfTeamDay(now).toISOString();
  const weekAgo = new Date(now.getTime() - 7 * 86_400_000).toISOString();
  const leads = () => supabase.from("leads").select("id", { count: "exact", head: true });

  const [newToday, highScoreToday, followupsDue, repliesWaiting, topToday] = await Promise.all([
    leads().gte("created_at", dayStart).then(count),
    leads().gte("created_at", dayStart).gte("fit_score", 8).then(count),
    supabase.from("v_followups_due").select("id", { count: "exact", head: true }).then(count),
    leads().eq("status", "replied").then(count),
    supabase
      .from("leads")
      .select(LEAD_SUMMARY)
      .gte("created_at", dayStart)
      .neq("status", "rejected")
      .order("fit_score", { ascending: false, nullsFirst: false })
      .limit(8)
      .then(rows),
  ]);

  const recent = topToday.length
    ? []
    : await supabase
        .from("leads")
        .select(LEAD_SUMMARY)
        .gte("created_at", weekAgo)
        .neq("status", "rejected")
        .order("fit_score", { ascending: false, nullsFirst: false })
        .limit(5)
        .then(rows);

  return { newToday, highScoreToday, followupsDue, repliesWaiting, topToday, recent };
}

export type HealthData = { runs: AgentRun[]; enabledSources: string[]; now: Date };

/** Runs from the last 30 days, newest first, and the sources switched on. */
export async function getHealth(): Promise<HealthData> {
  const { supabase } = await requireMember();
  const now = new Date();
  const since = new Date(now.getTime() - 30 * 86_400_000).toISOString();
  const [runs, configs] = await Promise.all([
    supabase
      .from("agent_runs")
      .select("*")
      .gte("started_at", since)
      .order("started_at", { ascending: false })
      .limit(500)
      .then(rows),
    supabase.from("source_configs").select("source").eq("enabled", true).then(rows),
  ]);
  return { runs, enabledSources: [...new Set(configs.map((c) => c.source))], now };
}
