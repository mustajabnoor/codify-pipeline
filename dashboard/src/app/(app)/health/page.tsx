import { AlertTriangle, ExternalLink } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { requireMember } from "@/lib/auth";
import {
  formatCost,
  MISSED_AFTER_HOURS,
  type RunRow,
  runErrors,
  sourceHealth,
  WINDOW_DAYS,
} from "@/lib/health";
import { formatDateTime, type LeadSource, SOURCE_LABELS } from "@/lib/labels";
import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Agent health" };

export default function HealthPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Agent health</h1>
        <p className="text-sm text-muted-foreground">
          Runs from the last {WINDOW_DAYS} days. Times are Karachi time.
        </p>
      </div>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading runs…</p>}>
        <Health />
      </Suspense>
    </div>
  );
}

const STATUS_TONE: Record<RunRow["status"], string> = {
  success: "bg-emerald-600 text-white",
  partial: "bg-amber-500 text-white",
  failed: "bg-destructive text-white",
  running: "bg-secondary text-secondary-foreground",
};

function RunStatus({ status }: { status: RunRow["status"] }) {
  return <Badge className={cn("border-transparent capitalize", STATUS_TONE[status])}>{status}</Badge>;
}

function sourceName(source: string): string {
  return SOURCE_LABELS[source as LeadSource] ?? source;
}

function duration(run: RunRow): string {
  if (!run.finished_at) return "";
  const seconds = Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

async function Health() {
  await requireMember();
  const supabase = await createClient();
  const now = new Date();
  const since = new Date(now.getTime() - WINDOW_DAYS * 86400_000).toISOString();
  const [runsResult, configsResult] = await Promise.all([
    supabase
      .from("agent_runs")
      .select(
        "id, source, status, started_at, finished_at, items_seen, leads_new, leads_updated, leads_skipped, errors, tokens_used, cost_estimate",
      )
      .gte("started_at", since)
      .order("started_at", { ascending: false })
      .limit(500),
    supabase.from("source_configs").select("source").eq("enabled", true),
  ]);
  if (runsResult.error) throw new Error(`Could not load runs: ${runsResult.error.message}`);
  if (configsResult.error) throw new Error(`Could not load sources: ${configsResult.error.message}`);

  const runs: RunRow[] = runsResult.data;
  const enabled = [...new Set(configsResult.data.map((c) => c.source))];
  const health = sourceHealth(runs, enabled, now);
  const recent = runs.filter((r) => r.source !== "fixture").slice(0, 20);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        {health.map((h) => (
          <Card key={h.source} className={cn(h.missed && "border-destructive")}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <span>{sourceName(h.source)}</span>
                {h.last ? <RunStatus status={h.last.status} /> : <Badge variant="outline">no runs</Badge>}
              </CardTitle>
              <CardDescription>
                {h.enabled ? "Enabled" : "Disabled"}
                {h.last && ` · last run ${formatDateTime(h.last.started_at)}`}
                {h.last && duration(h.last) && ` (${duration(h.last)})`}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {h.missed && (
                <p className="flex items-center gap-2 text-destructive">
                  <AlertTriangle className="size-4" aria-hidden />
                  No run in the last {MISSED_AFTER_HOURS}h. Check the GitHub Actions workflow.
                </p>
              )}
              {h.last && (
                <p className="text-muted-foreground">
                  Last run: seen {h.last.items_seen} · new {h.last.leads_new} · updated {h.last.leads_updated} ·
                  skipped {h.last.leads_skipped} · {h.last.tokens_used.toLocaleString("en-US")} tokens ·{" "}
                  {formatCost(Number(h.last.cost_estimate))}
                </p>
              )}
              <p>
                {WINDOW_DAYS} days: {h.week.runs} {h.week.runs === 1 ? "run" : "runs"}
                {h.week.failed > 0 && <span className="text-destructive"> ({h.week.failed} failed)</span>} ·{" "}
                {h.week.leadsNew} new leads · {formatCost(h.week.cost)}
              </p>
              {h.last && <Errors errors={h.last.errors} />}
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          {!recent.length && <p className="text-sm text-muted-foreground">No runs in the last {WINDOW_DAYS} days.</p>}
          <ul className="divide-y text-sm">
            {recent.map((r) => (
              <li key={r.id} className="space-y-1 py-3">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <RunStatus status={r.status} />
                  <span className="font-medium">{sourceName(r.source)}</span>
                  <span className="text-muted-foreground">{formatDateTime(r.started_at)}</span>
                  <span className="text-muted-foreground">
                    new {r.leads_new} · updated {r.leads_updated} · skipped {r.leads_skipped} ·{" "}
                    {formatCost(Number(r.cost_estimate))}
                  </span>
                </div>
                <Errors errors={r.errors} />
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function Errors({ errors }: { errors: RunRow["errors"] }) {
  const list = runErrors(errors);
  if (!list.length) return null;
  return (
    <details>
      <summary className="cursor-pointer text-destructive">
        {list.length} {list.length === 1 ? "error" : "errors"}
      </summary>
      <ul className="mt-2 space-y-2 text-muted-foreground">
        {list.map((e, i) => (
          <li key={i} className="break-words">
            {e.message}
            {e.link && (
              <a href={e.link} target="_blank" rel="noopener noreferrer" className="ml-1 inline-flex items-center underline">
                link <ExternalLink className="ml-0.5 size-3" aria-hidden />
              </a>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
