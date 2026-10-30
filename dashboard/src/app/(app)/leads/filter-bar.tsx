"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  LEAD_SOURCES,
  LEAD_STATUSES,
  SERVICE_LABELS,
  SERVICES,
  SOURCE_LABELS,
  STATUS_LABELS,
} from "@/lib/labels";
import { type LeadFilters, OPEN_STATUSES } from "@/lib/leads/filters";

const OPEN = OPEN_STATUSES.join(",");

function Select({
  name,
  label,
  value,
  options,
}: {
  name: string;
  label: string;
  value: string | undefined;
  options: [string, string][];
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <select
        name={name}
        defaultValue={value ?? ""}
        className="h-9 rounded-md border border-input bg-transparent px-2 text-sm text-foreground shadow-xs focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <option value="">Any</option>
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Filters write to the URL (empty ones left out); the server renders the list. */
export function FilterBar({
  filters,
  countries,
  owners,
}: {
  filters: LeadFilters;
  countries: string[];
  owners: string[];
}) {
  const router = useRouter();
  const active = [filters.status.length, filters.source, filters.minScore, filters.service, filters.country, filters.owner].filter(Boolean).length;
  // Phones show search plus a toggle; the menus open on demand (always shown from md up).
  const [open, setOpen] = useState(false);

  function apply(form: HTMLFormElement) {
    const params = new URLSearchParams();
    for (const [key, value] of new FormData(form)) {
      if (typeof value === "string" && value.trim()) params.set(key, value.trim());
    }
    router.push(params.size ? `/leads?${params}` : "/leads");
  }

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    apply(event.currentTarget);
  };

  const status = filters.status.join(",");
  return (
    <form
      key={JSON.stringify(filters)}
      onSubmit={onSubmit}
      onChange={(event) => {
        if ((event.target as HTMLElement).tagName === "SELECT") apply(event.currentTarget);
      }}
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-8"
    >
      <div className="col-span-2 flex items-end gap-2 sm:col-span-3 lg:col-span-2">
        <label className="flex flex-1 flex-col gap-1 text-xs text-muted-foreground">
          Search
          <Input name="q" type="search" placeholder="Company or domain" defaultValue={filters.q ?? ""} />
        </label>
        <Button
          type="button"
          variant="outline"
          className="md:hidden"
          aria-expanded={open}
          aria-controls="lead-filters"
          onClick={() => setOpen((o) => !o)}
        >
          Filters{active ? ` (${active})` : ""}
        </Button>
      </div>
      <div id="lead-filters" className={`${open ? "contents" : "hidden"} md:contents`}>
      <Select
        name="status"
        label="Status"
        value={status}
        options={[
          [OPEN, "Needs review"],
          ...LEAD_STATUSES.map((s): [string, string] => [s, STATUS_LABELS[s]]),
        ]}
      />
      <Select
        name="source"
        label="Source"
        value={filters.source}
        options={LEAD_SOURCES.map((s) => [s, SOURCE_LABELS[s]])}
      />
      <Select
        name="min_score"
        label="Score"
        value={filters.minScore?.toString()}
        options={[9, 8, 7, 6, 5, 4].map((n) => [String(n), `${n}+`])}
      />
      <Select name="service" label="Service" value={filters.service} options={SERVICES.map((s) => [s, SERVICE_LABELS[s]])} />
      <Select name="country" label="Country" value={filters.country} options={countries.map((c) => [c, c])} />
      <Select name="owner" label="Owner" value={filters.owner} options={owners.map((o) => [o, o])} />
      </div>
      <input type="hidden" name="sort" value={filters.sort === "newest" ? "newest" : ""} />
      <Button type="submit" className="sr-only">
        Search
      </Button>
    </form>
  );
}
