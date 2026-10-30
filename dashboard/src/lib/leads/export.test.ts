import ExcelJS from "exceljs";
import { describe, expect, it } from "vitest";

import { EXPORT_COLUMNS, type ExportLead, exportFilename, exportRow, toCsv, toXlsx } from "./export";

const lead: ExportLead = {
  id: "5c1d",
  company_name: "Acme, Inc.",
  domain: "acme.com",
  website: "https://acme.com",
  fit_score: 8,
  status: "new",
  first_source: "funding",
  service_fit: ["mvp", "ai_integration"],
  country: "Germany",
  city: null,
  industry: "fintech",
  company_size: "11-50",
  owner: null,
  pain_point: "Hiring a React developer",
  score_reason: "Funded and hiring.",
  funding_round: "Seed",
  funding_amount: 2000000,
  created_at: "2026-10-29T20:30:00Z",
  contacts: [
    { full_name: "Sam", role: "Engineer", email: null, email_status: "unverified", linkedin_url: null, is_primary: false },
    { full_name: "Dana Lee", role: "CEO", email: "dana@acme.com", email_status: "catch_all", linkedin_url: null, is_primary: true },
  ],
  outreach: [
    { subject: "Old", draft_body: "old", final_body: null, status: "draft", created_at: "2026-10-01T00:00:00Z" },
    { subject: "Your seed round", draft_body: "AI text", final_body: "Edited text", status: "draft", created_at: "2026-10-29T00:00:00Z" },
  ],
};

describe("exportRow", () => {
  it("maps a lead to one row per column", () => {
    const row = exportRow(lead, "https://pipeline.codify-labs.com");
    expect(row).toHaveLength(EXPORT_COLUMNS.length);
    const byColumn = Object.fromEntries(EXPORT_COLUMNS.map((c, i) => [c, row[i]]));
    expect(byColumn).toMatchObject({
      Company: "Acme, Inc.",
      Status: "New",
      Source: "Funding",
      Services: "MVP, AI integration",
      Contact: "Dana Lee",
      Email: "dana@acme.com",
      "Email status": "Catch-all",
      "Draft subject": "Your seed round",
      Draft: "Edited text",
      // 20:30 UTC is the next day in Karachi (UTC+5).
      Added: "30 Oct 2026",
      "Dashboard link": "https://pipeline.codify-labs.com/leads/5c1d",
    });
  });

  it("handles a lead with no contacts or draft", () => {
    const row = exportRow({ ...lead, contacts: [], outreach: [] }, "");
    expect(row[EXPORT_COLUMNS.indexOf("Contact")]).toBeNull();
    expect(row[EXPORT_COLUMNS.indexOf("Draft")]).toBeNull();
  });
});

describe("toCsv", () => {
  it("quotes, escapes and neutralises formulas", () => {
    const csv = toCsv([["Acme, Inc.", 'say "hi"', "=HYPERLINK(1)", "-5 widgets", 7, null, "two\nlines"]]);
    expect(csv.startsWith("﻿Company,Domain")).toBe(true);
    const line = csv.split("\r\n")[1];
    expect(line).toBe(`"Acme, Inc.","say ""hi""",'=HYPERLINK(1),'-5 widgets,7,,"two\nlines"`);
  });
});

describe("toXlsx", () => {
  it("writes a header row and one row per lead", async () => {
    const buffer = await toXlsx([exportRow(lead, "https://x"), exportRow(lead, "https://x")]);
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(buffer);
    const sheet = workbook.getWorksheet("Leads")!;
    expect(sheet.rowCount).toBe(3);
    expect(sheet.getRow(1).getCell(1).value).toBe("Company");
    expect(sheet.getRow(2).getCell(1).value).toBe("Acme, Inc.");
  });
});

it("names files by the Karachi date", () => {
  expect(exportFilename("xlsx", new Date("2026-10-29T20:00:00Z"))).toBe("leads-2026-10-30.xlsx");
});
