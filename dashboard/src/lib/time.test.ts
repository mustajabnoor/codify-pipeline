import { describe, expect, it } from "vitest";

import { formatAgo, formatDateTime, startOfTeamDay, tzOffsetMinutes } from "./time";

describe("team day (Asia/Karachi, UTC+5)", () => {
  it("knows Karachi is five hours ahead", () => {
    expect(tzOffsetMinutes(new Date("2026-10-30T12:00:00Z"))).toBe(300);
  });

  it("starts at 19:00 UTC the previous evening", () => {
    // 06:30 UTC is 11:30 in Karachi on the 30th.
    expect(startOfTeamDay(new Date("2026-10-30T06:30:00Z")).toISOString()).toBe(
      "2026-10-29T19:00:00.000Z",
    );
  });

  it("rolls over at Karachi midnight, not UTC midnight", () => {
    // 19:30 UTC on the 30th is already 00:30 on the 31st in Karachi.
    expect(startOfTeamDay(new Date("2026-10-30T19:30:00Z")).toISOString()).toBe(
      "2026-10-30T19:00:00.000Z",
    );
    // 18:59 UTC is still the 30th (23:59 in Karachi).
    expect(startOfTeamDay(new Date("2026-10-30T18:59:00Z")).toISOString()).toBe(
      "2026-10-29T19:00:00.000Z",
    );
  });

  it("works for zones behind UTC too", () => {
    expect(startOfTeamDay(new Date("2026-01-15T03:00:00Z"), "America/New_York").toISOString()).toBe(
      "2026-01-14T05:00:00.000Z",
    );
  });
});

describe("formatting", () => {
  it("shows Karachi wall time", () => {
    expect(formatDateTime("2026-10-30T06:36:31Z")).toBe("Fri 30 Oct, 11:36");
  });

  it("shows how long ago", () => {
    const now = new Date("2026-10-30T12:00:00Z");
    expect(formatAgo("2026-10-30T11:59:40Z", now)).toBe("just now");
    expect(formatAgo("2026-10-30T11:15:00Z", now)).toBe("45 min ago");
    expect(formatAgo("2026-10-30T09:00:00Z", now)).toBe("3 h ago");
    expect(formatAgo("2026-10-27T12:00:00Z", now)).toBe("3 days ago");
  });
});
