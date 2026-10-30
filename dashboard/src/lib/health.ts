import type { AgentRun } from "@/lib/database.types";

// Same rule as the Slack summary (agent/summary.py): a daily source with no run
// in this long missed its schedule.
export const MISSED_AFTER_HOURS = 26;

export type SourceHealth = {
  source: string;
  last: AgentRun | null;
  missed: boolean;
};

/** Latest run per source: every enabled source, plus any other source that ran. */
export function sourceHealth(runs: AgentRun[], enabledSources: string[], now: Date): SourceHealth[] {
  const latest = new Map<string, AgentRun>();
  for (const run of runs) {
    const seen = latest.get(run.source);
    if (!seen || run.started_at > seen.started_at) latest.set(run.source, run);
  }
  const sources = [...new Set([...enabledSources, ...latest.keys()])].sort();
  return sources.map((source) => {
    const last = latest.get(source) ?? null;
    const age = last ? (now.getTime() - new Date(last.started_at).getTime()) / 3_600_000 : Infinity;
    return { source, last, missed: age > MISSED_AFTER_HOURS };
  });
}

/** Total AI cost (USD) of runs started at or after `since`. */
export function costSince(runs: AgentRun[], since: Date): number {
  return runs
    .filter((r) => new Date(r.started_at) >= since)
    .reduce((sum, r) => sum + Number(r.cost_estimate || 0), 0);
}

export function formatUsd(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/** Human label for a source name: "job_posting" -> "Job posting". */
export function sourceLabel(source: string): string {
  const label = source.replace(/_/g, " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}
