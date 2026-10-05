import { describe, expect, it } from "vitest";
import { normalizeRegNo } from "./PatientStep";

describe("normalizeRegNo", () => {
  it.each([
    [" rc 123 ", "RC123"],
    ["RC00123", "RC00123"],
    ["Rc 5 5 5", "RC555"],
  ])("accepts %j as %s", (raw, expected) => {
    expect(normalizeRegNo(raw)).toBe(expected);
  });

  it.each(["", "   ", "12345", "RCX1", "RC-123", "RC/../1", "RC" + "1".repeat(31)])("refuses %j", (raw) => {
    expect(normalizeRegNo(raw)).toBeNull();
  });
});
