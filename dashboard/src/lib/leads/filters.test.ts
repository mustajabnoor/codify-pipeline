import { describe, expect, it } from "vitest";

import { cleanSearch, parseFilters, toSearchParams } from "./filters";

describe("parseFilters", () => {
  it("defaults to every lead, best score first", () => {
    expect(parseFilters({})).toEqual({ status: [], sort: "score", page: 1 } as never);
  });

  it("reads every filter", () => {
    const f = parseFilters({
      q: "acme",
      source: "funding",
      status: "new,reviewing",
      service: "shopify",
      country: "Germany",
      owner: "Mustajab",
      min_score: "7",
      sort: "newest",
      page: "3",
    });
    expect(f).toEqual({
      q: "acme",
      source: "funding",
      status: ["new", "reviewing"],
      service: "shopify",
      country: "Germany",
      owner: "Mustajab",
      minScore: 7,
      sort: "newest",
      page: 3,
    });
  });

  it("drops unknown or malformed values", () => {
    const f = parseFilters({
      source: "upwork",
      status: "new,bogus,new",
      service: "",
      min_score: "11",
      page: "-2",
      sort: "random",
    });
    expect(f).toEqual(parseFilters({ status: "new" }));
  });

  it("uses the first value of a repeated param", () => {
    expect(parseFilters({ source: ["social", "funding"] }).source).toBe("social");
  });

  it("round-trips through the URL", () => {
    const params = { q: "acme", status: "new,reviewing", min_score: "8", page: "2" };
    const f = parseFilters(params);
    expect(parseFilters(Object.fromEntries(toSearchParams(f)))).toEqual(f);
    expect(toSearchParams(parseFilters({})).toString()).toBe("");
  });
});

describe("cleanSearch", () => {
  it("strips filter syntax and wildcards", () => {
    expect(cleanSearch("acme.com")).toBe("acme.com");
    expect(cleanSearch("a%b*c,or(x)")).toBe("a b c or x");
    expect(cleanSearch("   ")).toBeUndefined();
  });
});
