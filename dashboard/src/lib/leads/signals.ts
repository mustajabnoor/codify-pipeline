// Readable facts from a signal's metadata (written by the agent's collectors).

import { formatDateTime } from "@/lib/labels";

const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

type Metadata = Record<string, unknown>;

/** Bookkeeping keys that say nothing about the lead. */
const HIDDEN = new Set(["ai_prompts", "feed", "enrichment"]);

function show(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (Array.isArray(value)) return value.map(show).filter(Boolean).join(", ") || null;
  if (typeof value === "number") return new Intl.NumberFormat("en-US").format(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return null;
  if (typeof value === "string" && ISO_TIMESTAMP.test(value)) return formatDateTime(value) || value;
  return String(value);
}

/** Label/value pairs to show under a signal, e.g. ["Employment type", "Contract"]. */
export function signalFacts(metadata: unknown): [string, string][] {
  if (!metadata || typeof metadata !== "object") return [];
  const facts: [string, string][] = [];
  for (const [key, value] of Object.entries(metadata as Metadata)) {
    const text = show(value);
    if (HIDDEN.has(key) || !text) continue;
    const label = key.replace(/_/g, " ");
    facts.push([label.charAt(0).toUpperCase() + label.slice(1), text]);
  }
  return facts;
}

/** One line on what the contact search did for this signal, if it ran. */
export function enrichmentSummary(metadata: unknown): string | null {
  const e = (metadata as Metadata | null)?.enrichment as Metadata | undefined;
  if (!e || typeof e !== "object") return null;
  if (typeof e.skipped === "string") return `Contact search skipped: ${e.skipped}.`;
  if (typeof e.error === "string") return `Contact search failed: ${e.error}`;
  const via = e.method === "email_finder" ? "by name" : "by domain";
  const verified = e.verified && typeof e.verified === "object" ? Object.entries(e.verified as Metadata) : [];
  const checks = verified.map(([email, verdict]) => `${email}: ${verdict}`).join(", ");
  if (e.found) return `Contact found ${via} (Hunter)${checks ? `; verified ${checks}` : ""}.`;
  return `No contact found ${via} (Hunter)${checks ? `; tried ${checks}` : ""}.`;
}
