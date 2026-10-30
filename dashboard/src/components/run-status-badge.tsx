import { Badge } from "@/components/ui/badge";
import type { RunStatus } from "@/lib/database.types";

const VARIANT = {
  success: "success",
  partial: "warning",
  failed: "destructive",
  running: "secondary",
} as const;

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Badge variant={VARIANT[status]}>{status}</Badge>;
}
