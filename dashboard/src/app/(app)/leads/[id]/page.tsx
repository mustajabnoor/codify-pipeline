import { ArrowLeft, ExternalLink } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { type ReactNode, Suspense } from "react";

import { EmailDot, ScoreBadge, StatusBadge } from "@/components/lead-badges";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { requireMember } from "@/lib/auth";
import {
  EMAIL_STATUS_LABELS,
  formatDate,
  formatDateTime,
  isoToDateInput,
  SERVICE_LABELS,
  SOURCE_LABELS,
} from "@/lib/labels";
import { getLead, type LeadDetail } from "@/lib/leads/detail";
import { enrichmentSummary, signalFacts } from "@/lib/leads/signals";
import { draftBody } from "@/lib/outreach";
import { createClient } from "@/lib/supabase/server";

import { LeadDetailsForm } from "./lead-details-form";
import { LeadReview, type ReviewDraft } from "./lead-review";

export const metadata: Metadata = { title: "Lead" };

export default function LeadPage({ params }: PageProps<"/leads/[id]">) {
  return (
    <div className="space-y-4">
      <Link href="/leads" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Leads
      </Link>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading lead…</p>}>
        <Lead params={params} />
      </Suspense>
    </div>
  );
}

async function Lead({ params }: Pick<PageProps<"/leads/[id]">, "params">) {
  await requireMember();
  const { id } = await params;
  const lead = await getLead(await createClient(), id);
  if (!lead) notFound();

  const latest = lead.outreach[0];
  const draft: ReviewDraft | null = latest
    ? {
        id: latest.id,
        channel: latest.channel,
        status: latest.status,
        subject: latest.subject ?? "",
        body: draftBody(latest.final_body ?? latest.draft_body),
        aiBody: draftBody(latest.draft_body),
        edited: latest.final_body !== null,
        editable: latest.status === "draft" || latest.status === "approved",
      }
    : null;

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h1 className="text-xl font-semibold">{lead.company_name}</h1>
          <p className="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
            {lead.website || lead.domain ? (
              <ExternalA href={lead.website ?? `https://${lead.domain}`}>{lead.domain ?? lead.website}</ExternalA>
            ) : (
              <span>No website known</span>
            )}
            <span>· {SOURCE_LABELS[lead.first_source]}</span>
            <span>· added {formatDate(lead.created_at)}</span>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusBadge status={lead.status} />
          <ScoreBadge score={lead.fit_score} />
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <LeadReview key={latest?.id ?? "none"} leadId={lead.id} status={lead.status} draft={draft} />
          <Assessment lead={lead} />
          <Signals signals={lead.signals} />
        </div>
        <div className="space-y-4">
          <Contacts contacts={lead.contacts} />
          <LeadDetailsForm
            leadId={lead.id}
            initial={{ owner: lead.owner ?? "", followUp: isoToDateInput(lead.next_follow_up_at), notes: lead.notes ?? "" }}
          />
          <Business lead={lead} />
          <Timeline activities={lead.activities} />
        </div>
      </div>
    </div>
  );
}

function ExternalA({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 underline">
      {children}
      <ExternalLink className="size-3" aria-hidden />
    </a>
  );
}

function Facts({ items }: { items: [string, ReactNode][] }) {
  const shown = items.filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {shown.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Assessment({ lead }: { lead: LeadDetail }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Why this lead</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {lead.pain_point && (
          <p>
            <span className="font-medium">Pain point: </span>
            {lead.pain_point}
          </p>
        )}
        {lead.score_reason && <p className="text-muted-foreground">{lead.score_reason}</p>}
        <div className="flex flex-wrap gap-1">
          {(lead.service_fit ?? []).map((s) => (
            <Badge key={s} variant="secondary">
              {SERVICE_LABELS[s]}
            </Badge>
          ))}
          {lead.best_channel && <Badge variant="outline">Best channel: {lead.best_channel.replace("_", " ")}</Badge>}
        </div>
      </CardContent>
    </Card>
  );
}

function Contacts({ contacts }: { contacts: LeadDetail["contacts"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Contacts</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {!contacts.length && <p className="text-muted-foreground">No contact found yet.</p>}
        {contacts.map((c) => (
          <div key={c.id} className="space-y-1">
            <p className="font-medium">
              {c.full_name ?? c.email ?? "Unnamed"}
              {c.is_primary && <span className="font-normal text-muted-foreground"> · primary</span>}
            </p>
            {c.role && <p className="text-muted-foreground">{c.role}</p>}
            {c.email && (
              <p className="flex items-center gap-1.5">
                <EmailDot status={c.email_status} />
                <a className="underline" href={`mailto:${c.email}`}>
                  {c.email}
                </a>
                <span className="text-xs text-muted-foreground">{EMAIL_STATUS_LABELS[c.email_status]}</span>
              </p>
            )}
            {(c.phone || c.whatsapp) && (
              <p className="text-muted-foreground">
                {[c.phone && `Phone ${c.phone}`, c.whatsapp && `WhatsApp ${c.whatsapp}`].filter(Boolean).join(" · ")}
              </p>
            )}
            <p className="flex flex-wrap gap-3">
              {c.linkedin_url && <ExternalA href={c.linkedin_url}>LinkedIn</ExternalA>}
              {c.x_url && <ExternalA href={c.x_url}>X</ExternalA>}
              {c.other_url && <ExternalA href={c.other_url}>Link</ExternalA>}
            </p>
            {c.found_via && <p className="text-xs text-muted-foreground">Found via {c.found_via}</p>}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Signals({ signals }: { signals: LeadDetail["signals"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Signals ({signals.length})</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5 text-sm">
        {signals.map((s) => {
          const enrichment = enrichmentSummary(s.metadata);
          return (
            <div key={s.id} className="space-y-2">
              <p className="text-xs text-muted-foreground">
                {SOURCE_LABELS[s.source]} · {s.signal_type.replace(/_/g, " ")} · {formatDateTime(s.detected_at)}
              </p>
              <p className="font-medium">
                <ExternalA href={s.source_url}>{s.title ?? s.source_url}</ExternalA>
              </p>
              <Facts items={signalFacts(s.metadata)} />
              {enrichment && <p className="text-xs text-muted-foreground">{enrichment}</p>}
              {s.raw_text && (
                <details>
                  <summary className="cursor-pointer text-muted-foreground">Full text</summary>
                  <p className="mt-2 max-h-96 overflow-y-auto whitespace-pre-line text-muted-foreground">{s.raw_text}</p>
                </details>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function Business({ lead }: { lead: LeadDetail }) {
  const funding = [
    lead.funding_round,
    lead.funding_amount && `$${new Intl.NumberFormat("en-US").format(lead.funding_amount)}`,
    lead.funding_date && formatDate(lead.funding_date),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Card>
      <CardHeader>
        <CardTitle>Business</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {lead.description && <p>{lead.description}</p>}
        <Facts
          items={[
            ["Industry", lead.industry],
            ["Location", [lead.city, lead.country].filter(Boolean).join(", ")],
            ["Size", lead.company_size],
            ["Funding", funding],
            ["Tech", (lead.tech_stack ?? []).join(", ")],
          ]}
        />
      </CardContent>
    </Card>
  );
}

function Timeline({ activities }: { activities: LeadDetail["activities"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Timeline</CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="space-y-3 text-sm">
          {activities.map((a) => (
            <li key={a.id}>
              <p>{a.note ?? a.type.replace(/_/g, " ")}</p>
              <p className="text-xs text-muted-foreground">
                {formatDateTime(a.created_at)} · {a.actor}
              </p>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
