import { RunStatusBadge } from "@/components/run-status";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime, type LeadSource, SOURCE_LABELS } from "@/lib/labels";
import { groupBySource, type PlatformRow, platformState } from "@/lib/platforms";

import { AiSwitch, PlatformSwitch } from "./switches";

/** The Sources page body: the Claude API switch, then each source's platforms. */
export function SourcesView({
  platforms: rows,
  aiEnabled,
  aiChangedBy,
  aiChangedAt,
  waiting,
  enabledSources,
}: {
  platforms: PlatformRow[];
  aiEnabled: boolean;
  aiChangedBy: string | null;
  aiChangedAt: string | null;
  /** New leads saved without a score (while AI was off). */
  waiting: number;
  /** Sources enabled in source_configs. */
  enabledSources: LeadSource[];
}) {
  const configOn = new Set(enabledSources);
  const groups = groupBySource(rows);

  return (
    <div className="space-y-4">
      <Card className={aiEnabled ? undefined : "border-amber-500"}>
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-3">
            <span>Claude API</span>
            <AiSwitch key={String(aiEnabled)} enabled={aiEnabled} />
          </CardTitle>
          <CardDescription>
            Scores each new lead, finds a contact for good ones and drafts the first message.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {aiEnabled ? (
            <p className="text-muted-foreground">On.</p>
          ) : (
            <p>
              <span className="font-medium">Off.</span> Runs still collect, but new leads are saved without a score,
              contact or draft, and sources that need Claude to read (funding news) are paused. When you switch it back
              on, each source&apos;s next run scores up to 20 waiting leads.
            </p>
          )}
          {waiting > 0 && (
            <p className="text-muted-foreground">
              {waiting} new {waiting === 1 ? "lead is" : "leads are"} waiting to be scored.
            </p>
          )}
          {aiChangedBy && (
            <p className="text-xs text-muted-foreground">
              Last changed by {aiChangedBy}, {formatDateTime(aiChangedAt)}
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {groups.map(({ source, platforms }) => {
          const built = platforms.some((p) => p.available);
          return (
            <Card key={source}>
              <CardHeader>
                <CardTitle>{SOURCE_LABELS[source]}</CardTitle>
                {built && !configOn.has(source) && (
                  <CardDescription className="text-amber-600">
                    This source is disabled in source_configs, so none of its platforms run.
                  </CardDescription>
                )}
                {!built && <CardDescription>Planned: not built yet.</CardDescription>}
              </CardHeader>
              <CardContent>
                <ul className="divide-y">
                  {platforms.map((p) => (
                    <Platform key={p.key} platform={p} aiEnabled={aiEnabled} />
                  ))}
                </ul>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function Platform({ platform: p, aiEnabled }: { platform: PlatformRow; aiEnabled: boolean }) {
  const state = platformState(p, aiEnabled);
  return (
    <li className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0 space-y-1 text-sm">
        <p className="flex flex-wrap items-center gap-2 font-medium">
          {p.name}
          {state === "unavailable" && <Badge variant="outline">Not available</Badge>}
          {state === "paused" && (
            <Badge className="border-transparent bg-amber-500 text-white">Paused: needs Claude</Badge>
          )}
          {state === "off" && <Badge variant="secondary">Off</Badge>}
        </p>
        {state !== "unavailable" &&
          (p.last_run_at && p.last_run_status ? (
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
              <RunStatusBadge status={p.last_run_status} />
              <span>{formatDateTime(p.last_run_at)}</span>
              {p.last_run_items !== null && (
                <span>
                  {p.last_run_items} {p.last_run_items === 1 ? "item" : "items"} · {p.last_run_leads_new ?? 0} new
                </span>
              )}
            </p>
          ) : (
            <p className="text-muted-foreground">No run yet</p>
          ))}
        {state !== "unavailable" && p.last_run_error && (
          <p className="line-clamp-2 break-words text-xs text-destructive" title={p.last_run_error}>
            {p.last_run_error}
          </p>
        )}
      </div>
      <PlatformSwitch
        key={String(p.enabled)}
        platformKey={p.key}
        name={p.name}
        enabled={p.enabled}
        available={p.available}
      />
    </li>
  );
}
