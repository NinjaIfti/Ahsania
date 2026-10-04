import { describe, expect, it } from "vitest";
import { ageLabel } from "./time";

const NOW = new Date("2026-10-04T12:00:00Z");

describe("ageLabel", () => {
  it.each([
    ["2026-10-04T11:59:40Z", "just now"],
    ["2026-10-04T11:45:00Z", "15 min"],
    ["2026-10-04T09:00:00Z", "3 h"],
    ["2026-10-02T13:00:00Z", "47 h"],
    ["2026-10-02T12:00:00Z", "2 d"],
    ["2026-09-30T12:00:00Z", "4 d"],
  ])("%s -> %s", (iso, label) => {
    expect(ageLabel(iso, NOW)).toBe(label);
  });
});
