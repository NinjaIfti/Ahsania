import { describe, expect, it } from "vitest";
import type { Extraction } from "../api/types";
import { aiMarker } from "./aiMarkers";

const HOSPITAL_VIEW: Extraction = {
  model: "m",
  fields: {
    modality: { colour: "green", confidence: 0.99, sources: [{ page: 1, box: [0, 0, 10, 10] }], edited: false, value: "CT" },
    contrast: { colour: "grey", confidence: null, sources: [], edited: false, value: null },
    impression: { colour: "amber", confidence: 0.5, sources: [], edited: true, value: "old text" },
  },
};

describe("aiMarker", () => {
  it("shows the AI result while the field holds what the AI filled in", () => {
    expect(aiMarker(HOSPITAL_VIEW, "modality", "CT")?.colour).toBe("green");
  });
  it("drops it as soon as the value changes, even before saving", () => {
    expect(aiMarker(HOSPITAL_VIEW, "modality", "MRI")).toBeNull();
  });
  it("keeps grey on a field that is still empty", () => {
    expect(aiMarker(HOSPITAL_VIEW, "contrast", undefined)?.colour).toBe("grey");
    expect(aiMarker(HOSPITAL_VIEW, "contrast", "")?.colour).toBe("grey");
    expect(aiMarker(HOSPITAL_VIEW, "contrast", true)).toBeNull();
  });
  it("drops it for a value saved after the AI", () => {
    expect(aiMarker(HOSPITAL_VIEW, "impression", "old text")).toBeNull();
  });
  it("has nothing for fields the AI did not fill or records it did not read", () => {
    expect(aiMarker(HOSPITAL_VIEW, "lesions[0].lobe", "RUL")).toBeNull();
    expect(aiMarker(null, "modality", "CT")).toBeNull();
  });
});
