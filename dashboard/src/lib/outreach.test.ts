import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { draftBody, SIGN_OFF, withSignOff, wordCount } from "./outreach";

describe("sign-off", () => {
  it("matches the agent's SIGN_OFF", () => {
    const models = readFileSync(fileURLToPath(new URL("../../../agent/core/models.py", import.meta.url)), "utf8");
    const python = models.match(/^SIGN_OFF = "(.*)"$/m)?.[1];
    expect(python?.replace(/\\n/g, "\n")).toBe(SIGN_OFF);
  });

  it("splits it off a stored draft and puts it back", () => {
    const stored = `Hi Dana,\n\nWorth a quick look?\n\n${SIGN_OFF}`;
    expect(draftBody(stored)).toBe("Hi Dana,\n\nWorth a quick look?");
    expect(withSignOff(draftBody(stored))).toBe(stored);
    expect(withSignOff("  edited text \r\n")).toBe(`edited text\n\n${SIGN_OFF}`);
  });

  it("leaves a draft without the sign-off alone", () => {
    expect(draftBody("Just text\n")).toBe("Just text");
    expect(draftBody(null)).toBe("");
  });
});

it("counts words", () => {
  expect(wordCount("  Hi Dana,\n\nworth a   look? ")).toBe(5);
  expect(wordCount("")).toBe(0);
});
