import type { Metadata } from "next";
import { Suspense } from "react";

import { requireMember } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";

import { SourcesView } from "./sources-view";

export const metadata: Metadata = { title: "Sources" };

export default function SourcesPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Sources</h1>
        <p className="text-sm text-muted-foreground">
          Switch each platform on or off. Changes apply from the source&apos;s next scheduled run. Times are Karachi
          time.
        </p>
      </div>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading sources…</p>}>
        <Sources />
      </Suspense>
    </div>
  );
}

const PLATFORM_COLUMNS =
  "key, source, name, available, enabled, needs_ai, sort_order, last_run_at, last_run_status, last_run_items, last_run_leads_new, last_run_error";

async function Sources() {
  await requireMember();
  const supabase = await createClient();
  const [platformsResult, settingsResult, configsResult, waitingResult] = await Promise.all([
    supabase.from("source_platforms").select(PLATFORM_COLUMNS),
    supabase.from("app_settings").select("ai_enabled, updated_by, updated_at").maybeSingle(),
    supabase.from("source_configs").select("source, enabled"),
    supabase.from("leads").select("id", { count: "exact", head: true }).is("fit_score", null).eq("status", "new"),
  ]);
  if (platformsResult.error) throw new Error(`Could not load platforms: ${platformsResult.error.message}`);
  if (settingsResult.error) throw new Error(`Could not load settings: ${settingsResult.error.message}`);
  if (configsResult.error) throw new Error(`Could not load source configs: ${configsResult.error.message}`);
  if (waitingResult.error) throw new Error(`Could not count unscored leads: ${waitingResult.error.message}`);

  return (
    <SourcesView
      platforms={platformsResult.data}
      aiEnabled={settingsResult.data?.ai_enabled ?? true}
      aiChangedBy={settingsResult.data?.updated_by ?? null}
      aiChangedAt={settingsResult.data?.updated_at ?? null}
      waiting={waitingResult.count ?? 0}
      enabledSources={configsResult.data.filter((c) => c.enabled).map((c) => c.source)}
    />
  );
}
