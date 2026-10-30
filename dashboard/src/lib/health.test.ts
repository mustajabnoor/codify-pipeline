import { describe, expect, it } from "vitest";

import { formatCost, type RunRow, runErrors, sourceHealth } from "./health";

const NOW = new Date("2026-10-30T12:00:00Z");

function run(source: string, started_at: string, extra: Partial<RunRow> = {}): RunRow {
  return {
    id: `${source}-${started_at}`,
    source,
    status: "success",
    started_at,
    finished_at: started_at,
    items_seen: 10,
    leads_new: 2,
    leads_updated: 0,
    leads_skipped: 8,
    errors: [],
    tokens_used: 1000,
    cost_estimate: 0.25,
    ...extra,
  };
}

describe("sourceHealth", () => {
  it("reports the latest run, weekly totals and missed sources", () => {
    const health = sourceHealth(
      [
        run("job_posting", "2026-10-29T03:00:00Z"),
        run("job_posting", "2026-10-30T03:00:00Z", { status: "partial", cost_estimate: 0.5 }),
        run("funding", "2026-10-28T03:30:00Z", { status: "failed", leads_new: 0 }),
        run("social", "2026-10-30T08:00:00Z"),
        run("fixture", "2026-10-30T09:00:00Z"),
      ],
      ["job_posting", "funding", "product_launch"],
      NOW,
    );
    expect(health.map((h) => [h.source, h.enabled, h.missed, h.last?.status ?? null])).toEqual([
      ["funding", true, true, "failed"], // last run > 26h ago
      ["job_posting", true, false, "partial"],
      ["product_launch", true, true, null], // never ran
      ["social", false, false, "success"], // disabled but ran: shown, never "missed"
    ]);
    expect(health[1].week).toEqual({ runs: 2, failed: 0, leadsNew: 4, cost: 0.75 });
    expect(health[0].week.failed).toBe(1);
  });
});

describe("runErrors", () => {
  it("reads the agent's error records and skips anything malformed", () => {
    expect(
      runErrors([
        { message: "HTTPError: 503", context: { feed: "https://x/feed" }, at: "2026-10-30T03:01:00Z" },
        { message: "AIError: declined", context: { source_url: "https://jobs/1", domain: "a.com" } },
        { message: "enrichment stopped", context: {} },
        { nope: true },
        "text",
      ]),
    ).toEqual([
      { message: "HTTPError: 503", at: "2026-10-30T03:01:00Z", link: "https://x/feed" },
      { message: "AIError: declined", at: null, link: "https://jobs/1" },
      { message: "enrichment stopped", at: null, link: null },
    ]);
    expect(runErrors(null)).toEqual([]);
  });
});

it("formats cost", () => {
  expect(formatCost(0.3062)).toBe("$0.31");
});
