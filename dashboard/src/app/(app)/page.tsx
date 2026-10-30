import { ExternalLink } from "lucide-react";
import type { Metadata } from "next";

import { ScoreBadge } from "@/components/score-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getToday, type LeadSummary } from "@/lib/data";
import { sourceLabel } from "@/lib/health";
import { formatAgo } from "@/lib/time";

export const metadata: Metadata = { title: "Today" };

export default async function TodayPage() {
  const today = await getToday();
  const kpis = [
    { label: "New leads today", value: today.newToday },
    { label: "Scored 8+ today", value: today.highScoreToday },
    { label: "Follow-ups due", value: today.followupsDue },
    { label: "Replies waiting", value: today.repliesWaiting },
  ];
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Today</h1>

      <section aria-label="Key numbers" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {kpis.map(({ label, value }) => (
          <Card key={label} className="gap-1 py-4">
            <CardContent className="flex flex-col gap-1 px-4">
              <span className="text-3xl font-semibold tabular-nums">{value}</span>
              <span className="text-sm text-muted-foreground">{label}</span>
            </CardContent>
          </Card>
        ))}
      </section>

      {today.topToday.length ? (
        <LeadList title="Top new leads today" leads={today.topToday} />
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>No new leads yet today</CardTitle>
              <CardDescription>
                Job posts run at 08:00 and funding news at 08:30 (Pakistan time).
              </CardDescription>
            </CardHeader>
          </Card>
          {today.recent.length ? (
            <LeadList title="Best leads from the last 7 days" leads={today.recent} />
          ) : null}
        </>
      )}
    </div>
  );
}

function LeadList({ title, leads }: { title: string; leads: LeadSummary[] }) {
  return (
    <section aria-label={title} className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      <Card className="py-0">
        <ul className="divide-y">
          {leads.map((lead) => (
            <LeadRow key={lead.id} lead={lead} />
          ))}
        </ul>
      </Card>
    </section>
  );
}

function LeadRow({ lead }: { lead: LeadSummary }) {
  const signal = [...lead.signals].sort((a, b) => a.detected_at.localeCompare(b.detected_at))[0];
  return (
    <li className="flex flex-col gap-1.5 px-4 py-3">
      <div className="flex items-center gap-2">
        <ScoreBadge score={lead.fit_score} />
        <span className="truncate font-medium">{lead.company_name}</span>
        {lead.domain ? (
          <span className="hidden truncate text-sm text-muted-foreground sm:inline">{lead.domain}</span>
        ) : null}
      </div>
      {lead.pain_point ? <p className="text-sm">{lead.pain_point}</p> : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>{sourceLabel(lead.first_source)}</span>
        {lead.funding_round ? <span>{lead.funding_round}</span> : null}
        <span>{formatAgo(lead.created_at)}</span>
        {signal ? (
          <a
            href={signal.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
          >
            {signal.title ? truncate(signal.title, 60) : "Source"}
            <ExternalLink className="size-3" />
          </a>
        ) : null}
      </div>
    </li>
  );
}

function truncate(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
