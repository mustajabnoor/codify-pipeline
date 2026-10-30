import { Badge } from "@/components/ui/badge";

/** Fit score 1-10: 8+ green, 4-7 neutral, 3 and below (auto-rejected) outline. */
export function ScoreBadge({ score }: { score: number | null }) {
  if (score == null) return <Badge variant="outline">–</Badge>;
  const variant = score >= 8 ? "success" : score >= 4 ? "secondary" : "outline";
  return (
    <Badge variant={variant} className="tabular-nums" aria-label={`Fit score ${score} of 10`}>
      {score}/10
    </Badge>
  );
}
