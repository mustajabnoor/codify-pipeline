import { Badge } from "@/components/ui/badge";
import { EMAIL_STATUS_LABELS, type EmailStatus, type LeadStatus, STATUS_LABELS } from "@/lib/labels";
import { cn } from "@/lib/utils";

export function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return <span className="text-muted-foreground">–</span>;
  const tone =
    score >= 8
      ? "bg-emerald-600 text-white"
      : score >= 6
        ? "bg-amber-500 text-white"
        : score >= 4
          ? "bg-secondary text-secondary-foreground"
          : "bg-destructive/15 text-destructive";
  return (
    <span
      className={cn("inline-flex size-7 items-center justify-center rounded-full text-xs font-semibold tabular-nums", tone)}
      aria-label={`Score ${score} of 10`}
    >
      {score}
    </span>
  );
}

export function StatusBadge({ status }: { status: LeadStatus }) {
  const variant = status === "rejected" || status === "lost" ? "outline" : status === "new" ? "default" : "secondary";
  return <Badge variant={variant}>{STATUS_LABELS[status]}</Badge>;
}

const EMAIL_DOT: Record<EmailStatus, string> = {
  valid: "bg-emerald-500",
  catch_all: "bg-amber-500",
  risky: "bg-amber-500",
  unverified: "bg-muted-foreground/50",
  invalid: "bg-destructive",
};

/** A small dot showing how far an email can be trusted. */
export function EmailDot({ status }: { status: EmailStatus }) {
  return (
    <span
      className={cn("inline-block size-2 shrink-0 rounded-full", EMAIL_DOT[status])}
      title={`Email: ${EMAIL_STATUS_LABELS[status]}`}
      aria-label={`Email ${EMAIL_STATUS_LABELS[status]}`}
    />
  );
}
