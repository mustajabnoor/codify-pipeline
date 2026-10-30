import type { NextRequest } from "next/server";

import { requireMember } from "@/lib/auth";
import { exportFilename, exportRow, toCsv, toXlsx } from "@/lib/leads/export";
import { parseFilters } from "@/lib/leads/filters";
import { allLeads, EXPORT_MAX_ROWS } from "@/lib/leads/query";
import { createClient } from "@/lib/supabase/server";

/** GET /leads/export?format=xlsx|csv&<list filters>: every lead the list
 * shows for those filters (all pages), as a file. */
export async function GET(request: NextRequest) {
  await requireMember();
  const params = Object.fromEntries(request.nextUrl.searchParams);
  const format = params.format === "csv" ? "csv" : "xlsx";
  const filters = { ...parseFilters(params), page: 1 };

  const supabase = await createClient();
  const { rows, total } = await allLeads(supabase, filters);
  const values = rows.map((lead) => exportRow(lead, request.nextUrl.origin));

  const headers = new Headers({
    "Content-Disposition": `attachment; filename="${exportFilename(format)}"`,
    "Cache-Control": "no-store",
    "X-Total-Leads": String(total),
  });
  if (total > EXPORT_MAX_ROWS) headers.set("X-Truncated-To", String(EXPORT_MAX_ROWS));
  if (format === "csv") {
    headers.set("Content-Type", "text/csv; charset=utf-8");
    return new Response(toCsv(values), { headers });
  }
  headers.set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  return new Response(await toXlsx(values), { headers });
}
