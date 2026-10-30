import { describe, expect, it } from "vitest";

import { dateInputToIso, formatDate, formatDateTime, isoToDateInput } from "./labels";

describe("Karachi dates", () => {
  it("formats in Asia/Karachi (UTC+5)", () => {
    expect(formatDate("2026-10-29T20:30:00Z")).toBe("30 Oct 2026");
    expect(formatDateTime("2026-10-29T20:30:00Z")).toBe("30 Oct, 01:30");
    expect(formatDate(null)).toBe("");
  });

  it("stores a follow-up day as 09:00 Karachi and reads it back", () => {
    expect(dateInputToIso("2026-11-02")).toBe("2026-11-02T04:00:00.000Z");
    expect(isoToDateInput("2026-11-02T04:00:00.000Z")).toBe("2026-11-02");
    expect(isoToDateInput("2026-11-01T20:00:00Z")).toBe("2026-11-02");
    expect(dateInputToIso("2026-13-40")).toBeNull();
    expect(dateInputToIso("")).toBeNull();
  });
});
