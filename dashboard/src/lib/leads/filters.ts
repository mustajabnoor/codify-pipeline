import { LEAD_SOURCES, LEAD_STATUSES, type LeadSource, type LeadStatus, SERVICES, type Service } from "@/lib/labels";

export const PAGE_SIZE = 50;
/** "Needs review": the statuses a new lead sits in until someone decides. */
export const OPEN_STATUSES: LeadStatus[] = ["new", "reviewing"];

export type Sort = "score" | "newest";

/** The Leads list's filters. They live in the URL, so a filtered view can be
 * bookmarked, and the export uses exactly what the list shows. */
export type LeadFilters = {
  source?: LeadSource;
  status: LeadStatus[];
  service?: Service;
  country?: string;
  owner?: string;
  q?: string;
  minScore?: number;
  sort: Sort;
  page: number;
};

type Params = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v?.trim() || undefined;
}

function oneOf<T extends string>(allowed: readonly T[], value: string | undefined): T | undefined {
  return allowed.find((a) => a === value);
}

/** Search text safe to put in a PostgREST filter: no wildcards or syntax. */
export function cleanSearch(value: string | undefined): string | undefined {
  const q = value?.replace(/[%*,()\\"']/g, " ").replace(/\s+/g, " ").trim().slice(0, 100);
  return q || undefined;
}

/** Unknown or malformed values are dropped rather than rejected, so an old
 * bookmark still opens. */
export function parseFilters(params: Params): LeadFilters {
  const status = (first(params.status) ?? "")
    .split(",")
    .map((s) => oneOf(LEAD_STATUSES, s.trim()))
    .filter((s): s is LeadStatus => Boolean(s));
  const score = Number(first(params.min_score));
  const page = Number(first(params.page));
  return {
    source: oneOf(LEAD_SOURCES, first(params.source)),
    status: [...new Set(status)],
    service: oneOf(SERVICES, first(params.service)),
    country: first(params.country)?.slice(0, 100),
    owner: first(params.owner)?.slice(0, 100),
    q: cleanSearch(first(params.q)),
    minScore: Number.isInteger(score) && score >= 1 && score <= 10 ? score : undefined,
    sort: first(params.sort) === "newest" ? "newest" : "score",
    page: Number.isInteger(page) && page > 1 ? page : 1,
  };
}

/** The URL query for a set of filters (defaults left out). */
export function toSearchParams(filters: LeadFilters): URLSearchParams {
  const out = new URLSearchParams();
  if (filters.q) out.set("q", filters.q);
  if (filters.source) out.set("source", filters.source);
  if (filters.status.length) out.set("status", filters.status.join(","));
  if (filters.service) out.set("service", filters.service);
  if (filters.country) out.set("country", filters.country);
  if (filters.owner) out.set("owner", filters.owner);
  if (filters.minScore) out.set("min_score", String(filters.minScore));
  if (filters.sort !== "score") out.set("sort", filters.sort);
  if (filters.page > 1) out.set("page", String(filters.page));
  return out;
}
