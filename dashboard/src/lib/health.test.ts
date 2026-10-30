import { describe, expect, it } from "vitest";

import type { AgentRun } from "./database.types";
import { costSince, MISSED_AFTER_HOURS, sourceHealth, sourceLabel } from "./health";

const NOW = new Date("2026-10-30T04:15:00Z");

function run(source: string, hoursAgo: number, extra: Partial<AgentRun> = {}): AgentRun {
  const at = new Date(NOW.getTime() - hoursAgo * 3_600_000).toISOString();
  return {
    id: `${source}-${hoursAgo}`,
    source,
    started_at: at,
    finished_at: at,
    status: "success",
    items_seen: 0,
    leads_new: 0,
    leads_updated: 0,
    leads_skipped: 0,
    errors: [],
    tokens_used: 0,
    cost_estimate: 0,
    created_at: at,
    updated_at: at,
    ...extra,
  };
}

describe("sourceHealth", () => {
  it("picks the latest run per source and lists enabled sources that never ran", () => {
    const runs = [run("funding", 30), run("funding", 1, { status: "partial" }), run("job_posting", 2)];
    const health = sourceHealth(runs, ["job_posting", "funding", "social"], NOW);
    expect(health.map((h) => [h.source, h.last?.status ?? null, h.missed])).toEqual([
      ["funding", "partial", false],
      ["job_posting", "success", false],
      ["social", null, true],
    ]);
  });

  it("flags a source with no run in 26 hours, like the Slack summary", () => {
    expect(MISSED_AFTER_HOURS).toBe(26);
    const [yesterday] = sourceHealth([run("job_posting", 25.25)], ["job_posting"], NOW);
    const [stale] = sourceHealth([run("funding", 27)], ["funding"], NOW);
    expect(yesterday.missed).toBe(false);
    expect(stale.missed).toBe(true);
  });

  it("also shows sources that ran but are no longer enabled", () => {
    const health = sourceHealth([run("fixture", 1)], ["job_posting"], NOW);
    expect(health.map((h) => h.source)).toEqual(["fixture", "job_posting"]);
  });
});

describe("costSince", () => {
  it("sums costs of runs in the window (Postgres numerics arrive as strings or numbers)", () => {
    const runs = [
      run("a", 1, { cost_estimate: 0.33 }),
      run("b", 2, { cost_estimate: "0.30" as unknown as number }),
      run("c", 24 * 8, { cost_estimate: 5 }),
    ];
    expect(costSince(runs, new Date(NOW.getTime() - 7 * 86_400_000))).toBeCloseTo(0.63);
  });
});

it("labels sources for people", () => {
  expect(sourceLabel("job_posting")).toBe("Job posting");
  expect(sourceLabel("funding")).toBe("Funding");
});
