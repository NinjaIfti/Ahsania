import { describe, expect, it } from "vitest";
import { getIn, humanize, pathToString, setIn } from "./fieldPaths";

describe("field paths", () => {
  it("formats paths like the server", () => {
    expect(pathToString(["lesions", 0, "long_axis_cm"])).toBe("lesions[0].long_axis_cm");
    expect(pathToString(["modality"])).toBe("modality");
  });
  it("reads nested values", () => {
    expect(getIn({ lesions: [{ lobe: "RUL" }] }, ["lesions", 0, "lobe"])).toBe("RUL");
    expect(getIn({}, ["lesions", 0, "lobe"])).toBeUndefined();
  });
  it("writes nested values without mutating the original", () => {
    const original = { modality: "CT", lesions: [{ lobe: "RUL" }] };
    const next = setIn(original, ["lesions", 1, "lobe"], "LUL");
    expect(next).toEqual({ modality: "CT", lesions: [{ lobe: "RUL" }, { lobe: "LUL" }] });
    expect(original.lesions).toHaveLength(1);
  });
  it("humanizes keys", () => {
    expect(humanize("long_axis_cm")).toBe("Long axis cm");
  });
});
