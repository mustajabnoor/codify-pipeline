import { describe, expect, it } from "vitest";

import { expectedSources, groupBySource, platformState } from "./platforms";

describe("platformState", () => {
  it("locks platforms that aren't built yet", () => {
    expect(platformState({ available: false, enabled: false, needs_ai: false }, true)).toBe("unavailable");
  });
  it("is off, on, or paused while AI is off", () => {
    expect(platformState({ available: true, enabled: false, needs_ai: true }, false)).toBe("off");
    expect(platformState({ available: true, enabled: true, needs_ai: false }, false)).toBe("on");
    expect(platformState({ available: true, enabled: true, needs_ai: true }, false)).toBe("paused");
    expect(platformState({ available: true, enabled: true, needs_ai: true }, true)).toBe("on");
  });
});

describe("groupBySource", () => {
  it("orders sources as the enum does and live platforms first", () => {
    const groups = groupBySource([
      { source: "social", name: "Reddit", available: false, sort_order: 10 },
      { source: "job_posting", name: "Wellfound", available: false, sort_order: 50 },
      { source: "job_posting", name: "We Work Remotely", available: true, sort_order: 20 },
      { source: "job_posting", name: "RemoteOK", available: true, sort_order: 10 },
    ]);
    expect(groups.map((g) => g.source)).toEqual(["job_posting", "social"]);
    expect(groups[0].platforms.map((p) => p.name)).toEqual(["RemoteOK", "We Work Remotely", "Wellfound"]);
  });
});

describe("expectedSources", () => {
  const platforms = [
    { source: "job_posting", enabled: false, needs_ai: false },
    { source: "job_posting", enabled: true, needs_ai: false },
    { source: "funding", enabled: true, needs_ai: true },
    { source: "social", enabled: false, needs_ai: false },
  ];
  const configs = ["job_posting", "funding", "social"];

  it("drops sources with every platform off", () => {
    expect(expectedSources(configs, platforms, true)).toEqual(["funding", "job_posting"]);
  });
  it("drops AI-only sources while AI is off", () => {
    expect(expectedSources(configs, platforms, false)).toEqual(["job_posting"]);
  });
  it("keeps sources without platform rows", () => {
    expect(expectedSources(["fixture"], platforms, false)).toEqual(["fixture"]);
  });
});
