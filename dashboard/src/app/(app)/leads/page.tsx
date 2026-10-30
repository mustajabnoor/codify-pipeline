import { Download } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { Button } from "@/components/ui/button";
import { requireMember } from "@/lib/auth";
import { type LeadFilters, PAGE_SIZE, parseFilters, toSearchParams } from "@/lib/leads/filters";
import { filterOptions, listLeads, primaryContact } from "@/lib/leads/query";
import { createClient } from "@/lib/supabase/server";

import { FilterBar } from "./filter-bar";
import { type ListLead, LeadsList } from "./leads-list";

export const metadata: Metadata = { title: "Leads" };

export default function LeadsPage({ searchParams }: PageProps<"/leads">) {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Leads</h1>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading leads…</p>}>
        <Leads searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

function href(filters: LeadFilters, changes: Partial<LeadFilters>): string {
  const qs = toSearchParams({ ...filters, ...changes }).toString();
  return qs ? `/leads?${qs}` : "/leads";
}

async function Leads({ searchParams }: Pick<PageProps<"/leads">, "searchParams">) {
  await requireMember();
  const filters = parseFilters(await searchParams);
  const supabase = await createClient();
  const [{ rows, total }, { countries, owners }] = await Promise.all([
    listLeads(supabase, filters),
    filterOptions(supabase),
  ]);

  const leads: ListLead[] = rows.map((row) => {
    const contact = primaryContact(row);
    return {
      id: row.id,
      company_name: row.company_name,
      domain: row.domain,
      fit_score: row.fit_score,
      status: row.status,
      first_source: row.first_source,
      service_fit: row.service_fit ?? [],
      country: row.country,
      created_at: row.created_at,
      pain_point: row.pain_point,
      contact: contact && { name: contact.full_name, email: contact.email, email_status: contact.email_status },
    };
  });

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const exportQs = toSearchParams({ ...filters, page: 1 });
  const exportHref = (format: string) => `/leads/export?${new URLSearchParams([...exportQs, ["format", format]])}`;

  return (
    <div className="space-y-4">
      <FilterBar filters={filters} countries={countries} owners={owners} />

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p className="text-muted-foreground">
          {total} {total === 1 ? "lead" : "leads"} · sorted by{" "}
          {filters.sort === "score" ? (
            <>
              score (<Link className="underline" href={href(filters, { sort: "newest", page: 1 })}>newest first</Link>)
            </>
          ) : (
            <>
              newest (<Link className="underline" href={href(filters, { sort: "score", page: 1 })}>best score first</Link>)
            </>
          )}
        </p>
        <div className="flex gap-2">
          <Button asChild variant="outline" size="sm">
            <a href={exportHref("xlsx")} download>
              <Download /> Excel
            </a>
          </Button>
          <Button asChild variant="outline" size="sm">
            <a href={exportHref("csv")} download>
              <Download /> CSV
            </a>
          </Button>
        </div>
      </div>

      <LeadsList key={exportQs.toString() + filters.page} leads={leads} />

      {pages > 1 && (
        <nav aria-label="Pages" className="flex items-center justify-between text-sm">
          {filters.page > 1 ? (
            <Link className="underline" href={href(filters, { page: filters.page - 1 })}>
              ← Previous
            </Link>
          ) : (
            <span />
          )}
          <span className="text-muted-foreground">
            Page {filters.page} of {pages}
          </span>
          {filters.page < pages ? (
            <Link className="underline" href={href(filters, { page: filters.page + 1 })}>
              Next →
            </Link>
          ) : (
            <span />
          )}
        </nav>
      )}
    </div>
  );
}
