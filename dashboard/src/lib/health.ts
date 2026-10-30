import type { Json } from "@/lib/database.types";

// Same rule as the Slack daily summary (agent/summary.py, MISSED_AFTER).
export const MISSED_AFTER_HOURS = 26;
export const WINDOW_DAYS = 7;

export type RunRow = {
  id: string;
  source: string;
  status: "running" | "success" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
  items_seen: number;
  leads_new: number;
  leads_updated: number;
  leads_skipped: number;
  errors: Json;
  tokens_used: number;
  cost_estimate: number;
};

export type SourceHealth = {
  source: string;
  enabled: boolean;
  last: RunRow | null;
  /** Enabled, but no run started in the last MISSED_AFTER_HOURS. */
  missed: boolean;
  week: { runs: number; failed: number; leadsNew: number; cost: number };
};

/** Health per source: every enabled source, plus any other source that ran
 * in the window (dev-only jobs like `fixture` are left out). Enabled
 * sources first, then by name. */
export function sourceHealth(runs: RunRow[], enabled: string[], now: Date): SourceHealth[] {
  const sources = new Set([...enabled, ...runs.map((r) => r.source)]);
  sources.delete("fixture");
  const missedBefore = now.getTime() - MISSED_AFTER_HOURS * 3600_000;
  return [...sources]
    .map((source) => {
      const own = runs
        .filter((r) => r.source === source)
        .sort((a, b) => b.started_at.localeCompare(a.started_at));
      const last = own[0] ?? null;
      const isEnabled = enabled.includes(source);
      return {
        source,
        enabled: isEnabled,
        last,
        missed: isEnabled && (!last || new Date(last.started_at).getTime() < missedBefore),
        week: {
          runs: own.length,
          failed: own.filter((r) => r.status === "failed").length,
          leadsNew: own.reduce((n, r) => n + r.leads_new, 0),
          cost: own.reduce((n, r) => n + Number(r.cost_estimate), 0),
        },
      };
    })
    .sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.source.localeCompare(b.source));
}

export type RunError = { message: string; at: string | null; link: string | null };

/** agent_runs.errors (written by the agent's RunRecorder) in a readable shape. */
export function runErrors(errors: Json): RunError[] {
  if (!Array.isArray(errors)) return [];
  return errors.flatMap((e) => {
    if (!e || typeof e !== "object" || Array.isArray(e) || typeof e.message !== "string") return [];
    const context = e.context && typeof e.context === "object" && !Array.isArray(e.context) ? e.context : {};
    const link = [context.source_url, context.url, context.feed].find((v) => typeof v === "string") ?? null;
    return [{ message: e.message, at: typeof e.at === "string" ? e.at : null, link: link as string | null }];
  });
}

export function formatCost(usd: number): string {
  return `$${usd.toFixed(2)}`;
}
