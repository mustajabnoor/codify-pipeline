import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { ScoreBadge } from "@/components/lead-badges";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { requireMember } from "@/lib/auth";
import { formatDate, isoToDateInput, SOURCE_LABELS } from "@/lib/labels";
import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = { title: "Today" };

const TOP_LEADS = 10;
const FOLLOW_UPS_SHOWN = 5;

export default function TodayPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Today</h1>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <Today />
      </Suspense>
    </div>
  );
}

async function Today() {
  await requireMember();
  const supabase = await createClient();
  const now = new Date();
  const today = isoToDateInput(now.toISOString()); // Karachi date, like v_daily_stats.day
  const dayAgo = new Date(now.getTime() - 86400_000).toISOString();

  const [daily, followUps, replied, top, waiting] = await Promise.all([
    supabase.from("v_daily_stats").select("new_leads, high_score_leads").eq("day", today),
    supabase
      .from("v_followups_due")
      .select("id, company_name, fit_score, next_follow_up_at", { count: "exact" })
      .order("next_follow_up_at", { ascending: true })
      .limit(FOLLOW_UPS_SHOWN),
    supabase.from("leads").select("id", { count: "exact", head: true }).eq("status", "replied"),
    supabase
      .from("leads")
      .select("id, company_name, domain, fit_score, pain_point, first_source")
      .eq("status", "new")
      .gte("created_at", dayAgo)
      .order("fit_score", { ascending: false, nullsFirst: false })
      .order("created_at", { ascending: false })
      .limit(TOP_LEADS),
    supabase.from("leads").select("id", { count: "exact", head: true }).in("status", ["new", "reviewing"]),
  ]);
  for (const result of [daily, followUps, replied, top, waiting]) {
    if (result.error) throw new Error(`Could not load today's numbers: ${result.error.message}`);
  }

  const newToday = (daily.data ?? []).reduce((n, r) => n + (r.new_leads ?? 0), 0);
  const highToday = (daily.data ?? []).reduce((n, r) => n + (r.high_score_leads ?? 0), 0);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="New leads today" value={newToday} href="/leads?sort=newest" />
        <Kpi label="Score 8+ today" value={highToday} href="/leads?min_score=8&sort=newest" />
        <Kpi label="Follow-ups due" value={followUps.count ?? 0} href="#follow-ups" />
        <Kpi label="Replies waiting" value={replied.count ?? 0} href="/leads?status=replied" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Top new leads</CardTitle>
          <CardDescription>
            Last 24 hours, best score first ·{" "}
            <Link className="underline" href="/leads?status=new%2Creviewing">
              {waiting.count ?? 0} waiting for review in total
            </Link>
          </CardDescription>
        </CardHeader>
        <CardContent>
          {top.data?.length ? (
            <ul className="divide-y">
              {top.data.map((lead) => (
                <li key={lead.id}>
                  <Link href={`/leads/${lead.id}`} className="flex items-start gap-3 py-3 hover:bg-accent/50">
                    <ScoreBadge score={lead.fit_score} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{lead.company_name}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {[lead.domain, SOURCE_LABELS[lead.first_source]].filter(Boolean).join(" · ")}
                      </p>
                      {lead.pain_point && (
                        <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{lead.pain_point}</p>
                      )}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No new leads in the last 24 hours.</p>
          )}
        </CardContent>
      </Card>

      <Card id="follow-ups">
        <CardHeader>
          <CardTitle>Follow-ups due</CardTitle>
        </CardHeader>
        <CardContent>
          {followUps.data?.length ? (
            <ul className="divide-y text-sm">
              {followUps.data.map((lead) => (
                <li key={lead.id}>
                  <Link href={`/leads/${lead.id}`} className="flex items-center justify-between gap-3 py-2 hover:bg-accent/50">
                    <span className="truncate font-medium">{lead.company_name}</span>
                    <span className="shrink-0 text-muted-foreground">due {formatDate(lead.next_follow_up_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Nothing due. Set a follow-up date on a lead to see it here.</p>
          )}
          {(followUps.count ?? 0) > FOLLOW_UPS_SHOWN && (
            <p className="mt-2 text-xs text-muted-foreground">
              Showing the {FOLLOW_UPS_SHOWN} oldest of {followUps.count}.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Kpi({ label, value, href }: { label: string; value: number; href: string }) {
  return (
    <Link href={href} className="rounded-xl focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none">
      <Card className="h-full transition-colors hover:bg-accent/50">
        <CardHeader>
          <CardDescription>{label}</CardDescription>
          <CardTitle className="text-3xl tabular-nums">{value}</CardTitle>
        </CardHeader>
      </Card>
    </Link>
  );
}
