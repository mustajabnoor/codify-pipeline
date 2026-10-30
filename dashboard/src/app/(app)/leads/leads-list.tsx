"use client";

import { useState, useTransition } from "react";

import { EmailDot, ScoreBadge, StatusBadge } from "@/components/lead-badges";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  type EmailStatus,
  formatDate,
  type LeadSource,
  type LeadStatus,
  type Service,
  SERVICE_LABELS,
  SOURCE_LABELS,
} from "@/lib/labels";

import { type BulkResult, setLeadsStatus } from "./actions";

/** What the list shows per lead (kept small: it is sent to the browser). */
export type ListLead = {
  id: string;
  company_name: string;
  domain: string | null;
  fit_score: number | null;
  status: LeadStatus;
  first_source: LeadSource;
  service_fit: Service[];
  country: string | null;
  created_at: string;
  pain_point: string | null;
  contact: { name: string | null; email: string | null; email_status: EmailStatus } | null;
};

function Contact({ contact }: { contact: ListLead["contact"] }) {
  if (!contact) return <span className="text-muted-foreground">–</span>;
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      {contact.email && <EmailDot status={contact.email_status} />}
      <span className="truncate">{contact.name ?? contact.email}</span>
    </span>
  );
}

function Services({ services }: { services: Service[] }) {
  return <span className="text-muted-foreground">{services.map((s) => SERVICE_LABELS[s]).join(", ")}</span>;
}

export function LeadsList({ leads }: { leads: ListLead[] }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<(BulkResult & { action: string }) | null>(null);
  const [pending, startTransition] = useTransition();

  const toggle = (id: string, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const allOn = leads.length > 0 && leads.every((l) => selected.has(l.id));
  const toggleAll = (on: boolean) => setSelected(on ? new Set(leads.map((l) => l.id)) : new Set());

  const run = (status: "approved" | "rejected") =>
    startTransition(async () => {
      const res = await setLeadsStatus([...selected], status);
      setResult({ ...res, action: status === "approved" ? "Approved" : "Rejected" });
      if (!res.error) setSelected(new Set());
    });

  if (!leads.length) {
    return <p className="py-12 text-center text-sm text-muted-foreground">No leads match these filters.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex min-h-9 flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-2">
          <Checkbox checked={allOn} onCheckedChange={(v) => toggleAll(v === true)} aria-label="Select all on this page" />
          {selected.size ? `${selected.size} selected` : "Select all"}
        </label>
        {selected.size > 0 && (
          <>
            <Button size="sm" disabled={pending} onClick={() => run("approved")}>
              Approve
            </Button>
            <Button size="sm" variant="outline" disabled={pending} onClick={() => run("rejected")}>
              Reject
            </Button>
          </>
        )}
        {result && (
          <span role="status" className={result.error ? "text-destructive" : "text-muted-foreground"}>
            {result.error ??
              `${result.action} ${result.changed}${result.skipped ? `; ${result.skipped} skipped (already decided)` : ""}.`}
          </span>
        )}
      </div>

      {/* Phones: cards */}
      <ul className="divide-y rounded-lg border md:hidden">
        {leads.map((lead) => (
          <li key={lead.id} className="flex gap-3 p-3">
            <Checkbox
              className="mt-1"
              checked={selected.has(lead.id)}
              onCheckedChange={(v) => toggle(lead.id, v === true)}
              aria-label={`Select ${lead.company_name}`}
            />
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-medium">{lead.company_name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {[lead.domain, SOURCE_LABELS[lead.first_source], lead.country].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <ScoreBadge score={lead.fit_score} />
              </div>
              {lead.pain_point && <p className="line-clamp-2 text-sm text-muted-foreground">{lead.pain_point}</p>}
              <div className="flex items-center justify-between gap-2 text-sm">
                <Contact contact={lead.contact} />
                <StatusBadge status={lead.status} />
              </div>
            </div>
          </li>
        ))}
      </ul>

      {/* Desktop: table */}
      <div className="hidden rounded-lg border md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>Company</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Services</TableHead>
              <TableHead>Country</TableHead>
              <TableHead>Contact</TableHead>
              <TableHead>Added</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {leads.map((lead) => (
              <TableRow key={lead.id} data-state={selected.has(lead.id) ? "selected" : undefined}>
                <TableCell>
                  <Checkbox
                    checked={selected.has(lead.id)}
                    onCheckedChange={(v) => toggle(lead.id, v === true)}
                    aria-label={`Select ${lead.company_name}`}
                  />
                </TableCell>
                <TableCell className="max-w-64">
                  <p className="truncate font-medium">{lead.company_name}</p>
                  <p className="truncate text-xs text-muted-foreground">{lead.domain}</p>
                </TableCell>
                <TableCell>
                  <ScoreBadge score={lead.fit_score} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={lead.status} />
                </TableCell>
                <TableCell>{SOURCE_LABELS[lead.first_source]}</TableCell>
                <TableCell className="max-w-48 truncate">
                  <Services services={lead.service_fit} />
                </TableCell>
                <TableCell>{lead.country}</TableCell>
                <TableCell className="max-w-48">
                  <Contact contact={lead.contact} />
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(lead.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
