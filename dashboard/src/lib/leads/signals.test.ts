import { describe, expect, it } from "vitest";

import { enrichmentSummary, signalFacts } from "./signals";

describe("signalFacts", () => {
  it("shows useful metadata and hides bookkeeping", () => {
    const facts = signalFacts({
      feed: "https://x/feed",
      ai_prompts: { score: "score_v2" },
      amount: 1700000,
      currency: "EUR",
      investors: ["Kaknäs Invest", "Other VC"],
      employment_type: "Contract",
      published_at: "2026-10-29T09:30:00+00:00",
      empty: [],
      nested: { a: 1 },
    });
    expect(facts).toEqual([
      ["Amount", "1,700,000"],
      ["Currency", "EUR"],
      ["Investors", "Kaknäs Invest, Other VC"],
      ["Employment type", "Contract"],
      ["Published at", "29 Oct, 14:30"],
    ]);
    expect(signalFacts(null)).toEqual([]);
  });
});

describe("enrichmentSummary", () => {
  it("describes each outcome", () => {
    expect(enrichmentSummary({})).toBeNull();
    expect(enrichmentSummary({ enrichment: { skipped: "score below 6" } })).toBe(
      "Contact search skipped: score below 6.",
    );
    expect(
      enrichmentSummary({
        enrichment: { provider: "hunter", method: "email_finder", found: true, verified: { "a@x.com": "catch_all" } },
      }),
    ).toBe("Contact found by name (Hunter); verified a@x.com: catch_all.");
    expect(enrichmentSummary({ enrichment: { method: "domain_search", found: false } })).toBe(
      "No contact found by domain (Hunter).",
    );
    expect(enrichmentSummary({ enrichment: { error: "Hunter returned HTTP 429" } })).toBe(
      "Contact search failed: Hunter returned HTTP 429",
    );
  });
});
