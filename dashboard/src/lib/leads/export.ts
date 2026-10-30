import {
  EMAIL_STATUS_LABELS,
  type EmailStatus,
  formatDate,
  type LeadSource,
  type LeadStatus,
  type Service,
  SERVICE_LABELS,
  SOURCE_LABELS,
  STATUS_LABELS,
} from "@/lib/labels";

/** The fields of a lead the export reads (a subset of the list query's row). */
export type ExportLead = {
  id: string;
  company_name: string;
  domain: string | null;
  website: string | null;
  fit_score: number | null;
  status: LeadStatus;
  first_source: LeadSource;
  service_fit: Service[] | null;
  country: string | null;
  city: string | null;
  industry: string | null;
  company_size: string | null;
  owner: string | null;
  pain_point: string | null;
  score_reason: string | null;
  funding_round: string | null;
  funding_amount: number | null;
  created_at: string;
  contacts: {
    full_name: string | null;
    role: string | null;
    email: string | null;
    email_status: EmailStatus;
    linkedin_url: string | null;
    is_primary: boolean;
  }[];
  outreach: { subject: string | null; draft_body: string | null; final_body: string | null; status: string; created_at: string }[];
};

type Cell = string | number | null;

export const EXPORT_COLUMNS = [
  "Company",
  "Domain",
  "Website",
  "Score",
  "Status",
  "Source",
  "Services",
  "Country",
  "City",
  "Industry",
  "Company size",
  "Owner",
  "Pain point",
  "Score reason",
  "Funding round",
  "Funding (USD)",
  "Contact",
  "Role",
  "Email",
  "Email status",
  "LinkedIn",
  "Draft subject",
  "Draft",
  "Added",
  "Dashboard link",
] as const;

/** One spreadsheet row per lead. The draft is the edited text when there is
 * one, else the AI's original. */
export function exportRow(lead: ExportLead, siteUrl: string): Cell[] {
  const contact =
    lead.contacts.find((c) => c.is_primary) ?? lead.contacts.find((c) => c.email) ?? lead.contacts[0];
  const draft = [...lead.outreach].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  return [
    lead.company_name,
    lead.domain,
    lead.website,
    lead.fit_score,
    STATUS_LABELS[lead.status],
    SOURCE_LABELS[lead.first_source],
    (lead.service_fit ?? []).map((s) => SERVICE_LABELS[s]).join(", "),
    lead.country,
    lead.city,
    lead.industry,
    lead.company_size,
    lead.owner,
    lead.pain_point,
    lead.score_reason,
    lead.funding_round,
    lead.funding_amount,
    contact?.full_name ?? null,
    contact?.role ?? null,
    contact?.email ?? null,
    contact?.email ? EMAIL_STATUS_LABELS[contact.email_status] : null,
    contact?.linkedin_url ?? null,
    draft?.subject ?? null,
    draft ? (draft.final_body ?? draft.draft_body) : null,
    formatDate(lead.created_at),
    `${siteUrl}/leads/${lead.id}`,
  ];
}

// Spreadsheet apps run cells starting with these as formulas.
const FORMULA_START = /^[=+\-@\t\r]/;

function csvCell(value: Cell): string {
  if (value === null) return "";
  let text = String(value);
  if (typeof value === "string" && FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** RFC 4180 CSV with a BOM so Excel reads it as UTF-8. */
export function toCsv(rows: Cell[][]): string {
  const lines = [EXPORT_COLUMNS as readonly Cell[], ...rows].map((r) => r.map(csvCell).join(","));
  return `﻿${lines.join("\r\n")}\r\n`;
}

/** An .xlsx workbook; cells are written as plain values, never formulas. */
export async function toXlsx(rows: Cell[][]): Promise<ArrayBuffer> {
  const { default: ExcelJS } = await import("exceljs");
  const workbook = new ExcelJS.Workbook();
  const sheet = workbook.addWorksheet("Leads", { views: [{ state: "frozen", ySplit: 1 }] });
  sheet.addRow([...EXPORT_COLUMNS]).font = { bold: true };
  for (const row of rows) sheet.addRow(row);
  sheet.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: EXPORT_COLUMNS.length } };
  sheet.columns.forEach((column, i) => {
    const wide = ["Pain point", "Score reason", "Draft"].includes(EXPORT_COLUMNS[i]);
    column.width = wide ? 60 : 18;
  });
  const buffer = await workbook.xlsx.writeBuffer();
  return buffer as ArrayBuffer;
}

export function exportFilename(format: "csv" | "xlsx", now = new Date()): string {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Karachi" }).format(now);
  return `leads-${day}.${format}`;
}
