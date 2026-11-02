import type { Database } from "@/lib/database.types";
import { LEAD_SOURCES, type LeadSource } from "@/lib/labels";

type RunStatus = Database["public"]["Enums"]["run_status"];

/** A source_platforms row as the Sources page reads it. */
export type PlatformRow = {
  key: string;
  source: LeadSource;
  name: string;
  available: boolean;
  enabled: boolean;
  needs_ai: boolean;
  sort_order: number;
  last_run_at: string | null;
  last_run_status: RunStatus | null;
  last_run_items: number | null;
  last_run_leads_new: number | null;
  last_run_error: string | null;
};

/**
 * What a platform is doing now:
 * - unavailable: not built yet (its switch is locked off)
 * - off: switched off
 * - paused: switched on, but it needs Claude AI and AI is off
 * - on: collects on its source's next run
 */
export type PlatformState = "unavailable" | "off" | "paused" | "on";

export function platformState(row: Pick<PlatformRow, "available" | "enabled" | "needs_ai">, aiEnabled: boolean): PlatformState {
  if (!row.available) return "unavailable";
  if (!row.enabled) return "off";
  if (row.needs_ai && !aiEnabled) return "paused";
  return "on";
}

/** Platforms grouped by source, sources in the usual order, live ones first. */
export function groupBySource<T extends Pick<PlatformRow, "source" | "available" | "sort_order" | "name">>(
  rows: T[],
): { source: LeadSource; platforms: T[] }[] {
  return LEAD_SOURCES.map((source) => ({
    source,
    platforms: rows
      .filter((r) => r.source === source)
      .sort(
        (a, b) =>
          Number(b.available) - Number(a.available) || a.sort_order - b.sort_order || a.name.localeCompare(b.name),
      ),
  })).filter((group) => group.platforms.length > 0);
}

/**
 * Sources that should run on schedule: enabled in source_configs, with at
 * least one platform switched on (when they have platforms), and not paused
 * because every platform switched on needs AI while AI is off. Mirrors
 * expected_sources in agent/core/db.py (the Slack summary uses that one).
 */
export function expectedSources(
  enabledConfigs: string[],
  platforms: { source: string; enabled: boolean; needs_ai: boolean }[],
  aiEnabled: boolean,
): string[] {
  return [...new Set(enabledConfigs)]
    .filter((source) => {
      const own = platforms.filter((p) => p.source === source);
      const on = own.filter((p) => p.enabled);
      if (own.length && !on.length) return false;
      return aiEnabled || !on.length || !on.every((p) => p.needs_ai);
    })
    .sort();
}
