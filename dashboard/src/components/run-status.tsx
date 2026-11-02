import { Badge } from "@/components/ui/badge";
import type { Database } from "@/lib/database.types";
import { cn } from "@/lib/utils";

type Status = Database["public"]["Enums"]["run_status"];

const STATUS_TONE: Record<Status, string> = {
  success: "bg-emerald-600 text-white",
  partial: "bg-amber-500 text-white",
  failed: "bg-destructive text-white",
  running: "bg-secondary text-secondary-foreground",
};

/** An agent run's status (agent_runs / source_platforms). */
export function RunStatusBadge({ status }: { status: Status }) {
  return <Badge className={cn("border-transparent capitalize", STATUS_TONE[status])}>{status}</Badge>;
}
