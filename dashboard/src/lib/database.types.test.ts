import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, it } from "vitest";

import { ENUMS } from "./database.types";

const MIGRATIONS = fileURLToPath(new URL("../../../supabase/migrations/", import.meta.url));

/** Every `create type public.<name> as enum (...)` in the migrations. */
function enumsInMigrations(): Record<string, string[]> {
  const sql = readdirSync(MIGRATIONS)
    .filter((f) => f.endsWith(".sql"))
    .sort()
    .map((f) => readFileSync(MIGRATIONS + f, "utf8"))
    .join("\n");
  const found: Record<string, string[]> = {};
  for (const match of sql.matchAll(/create type public\.(\w+) as enum \(([^)]*)\)/g)) {
    found[match[1]] = [...match[2].matchAll(/'([^']+)'/g)].map((m) => m[1]);
  }
  return found;
}

it("TypeScript enums match the database migrations", () => {
  expect(ENUMS).toEqual(enumsInMigrations());
});
