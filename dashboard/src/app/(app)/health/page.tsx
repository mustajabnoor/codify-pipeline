import { AlertTriangle } from "lucide-react";
import type { Metadata } from "next";

import { RunStatusBadge } from "@/components/run-status-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getHealth } from "@/lib/data";
import type { AgentRun } from "@/lib/database.types";
import {
  costSince,
  formatUsd,
  MISSED_AFTER_HOURS,
  sourceHealth,
  sourceLabel,
  type SourceHealth,
} from "@/lib/health";
import { formatAgo, formatDateTime } from "@/lib/time";

export const metadata: Metadata = { title: "Agent health" };

const DAY = 86_400_000;

export default async function HealthPage() {
  const { runs, enabledSources, now } = await getHealth();
  const sources = sourceHealth(runs, enabledSources, now);
  const recent = runs.filter((r) => new Date(r.started_at).getTime() >= now.getTime() - 14 * DAY);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Agent health</h1>
        <p className="text-sm text-muted-foreground">
          AI cost: {formatUsd(costSince(runs, new Date(now.getTime() - 7 * DAY)))} last 7 days ·{" "}
          {formatUsd(costSince(runs, new Date(now.getTime() - 30 * DAY)))} last 30 days
        </p>
      </div>

      <section aria-label="Sources" className="grid gap-3 md:grid-cols-2">
        {sources.length ? (
          sources.map((s) => <SourceCard key={s.source} health={s} />)
        ) : (
          <p className="text-sm text-muted-foreground">No sources are enabled.</p>
        )}
      </section>

      <section aria-label="Recent runs" className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Runs, last 14 days</h2>
        <Card className="py-0">
          {recent.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Started</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">New</TableHead>
                  <TableHead className="text-right">Updated</TableHead>
                  <TableHead className="text-right">Errors</TableHead>
                  <TableHead className="pr-4 text-right">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recent.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell className="pl-4">{formatDateTime(run.started_at)}</TableCell>
                    <TableCell>{sourceLabel(run.source)}</TableCell>
                    <TableCell>
                      <RunStatusBadge status={run.status} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{run.leads_new}</TableCell>
                    <TableCell className="text-right tabular-nums">{run.leads_updated}</TableCell>
                    <TableCell className="text-right tabular-nums">{run.errors.length}</TableCell>
                    <TableCell className="pr-4 text-right tabular-nums">
                      {formatUsd(Number(run.cost_estimate))}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="p-4 text-sm text-muted-foreground">No runs in the last 14 days.</p>
          )}
        </Card>
      </section>
    </div>
  );
}

function SourceCard({ health }: { health: SourceHealth }) {
  const { source, last, missed } = health;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>{sourceLabel(source)}</CardTitle>
          {last ? <RunStatusBadge status={last.status} /> : <Badge variant="outline">never ran</Badge>}
        </div>
        <CardDescription>
          {last ? (
            <>
              Last run {formatAgo(last.started_at)} ({formatDateTime(last.started_at)})
            </>
          ) : (
            "No runs recorded yet"
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {missed ? (
          <p className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="size-4" />
            No run in the last {MISSED_AFTER_HOURS} hours
          </p>
        ) : null}
        {last ? <RunCounts run={last} /> : null}
        {last?.errors.length ? <RunErrors run={last} /> : null}
      </CardContent>
    </Card>
  );
}

function RunCounts({ run }: { run: AgentRun }) {
  const items = [
    ["seen", run.items_seen],
    ["new", run.leads_new],
    ["updated", run.leads_updated],
    ["skipped", run.leads_skipped],
  ] as const;
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
      {items.map(([label, value]) => (
        <div key={label} className="flex gap-1">
          <dd className="font-medium tabular-nums text-foreground">{value}</dd>
          <dt>{label}</dt>
        </div>
      ))}
      <div className="flex gap-1">
        <dd className="font-medium tabular-nums text-foreground">{formatUsd(Number(run.cost_estimate))}</dd>
        <dt>AI cost</dt>
      </div>
    </dl>
  );
}

function RunErrors({ run }: { run: AgentRun }) {
  return (
    <details className="rounded-md border p-3">
      <summary className="cursor-pointer font-medium">
        {run.errors.length} error{run.errors.length === 1 ? "" : "s"} in the last run
      </summary>
      <ul className="mt-2 flex flex-col gap-2">
        {run.errors.slice(0, 20).map((error, i) => (
          <li key={i} className="break-words font-mono text-xs text-muted-foreground">
            {error.message}
          </li>
        ))}
      </ul>
    </details>
  );
}
