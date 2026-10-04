import { describe, expect, it } from "vitest";
import { lineNeedsRedaction, suggestBoxes } from "./labels";

describe("lineNeedsRedaction", () => {
  it.each([
    "Patient Name: Rahim Uddin",
    "Name : Test Person",
    "Pt. Name: X",
    "Mobile: 01712345678",
    "Contact 017-1234-5678",
    "Call +8801812345678 for results",
    "S/O: Abdul Karim",
    "Reg No: AMH-00123",
    "Date: 01/09/2026   Patient Name: Test Person",
    "UHID 99881",
    "Father's name Karim",
    "Address: House 5, Road 2, Uttara",
  ])("hides %s", (line) => {
    expect(lineNeedsRedaction(line)).toBe(true);
  });

  it.each([
    "Findings: 2.3 x 1.8 cm spiculated mass in right upper lobe.",
    "Impression: Suspicious for primary lung malignancy.",
    "Date: 01/09/2026",
    "Identification of a new nodule",
    "Region of interest drawn on axial image 42",
    "CT CHEST WITH CONTRAST",
  ])("keeps %s", (line) => {
    expect(lineNeedsRedaction(line)).toBe(false);
  });
});

describe("suggestBoxes", () => {
  it("pads each matching line and clamps at the image edge", () => {
    const boxes = suggestBoxes([
      { text: "Patient Name: Test", bbox: { x0: 2, y0: 20, x1: 110, y1: 40 } },
      { text: "Findings: mass", bbox: { x0: 10, y0: 60, x1: 200, y1: 80 } },
    ]);
    // x0=2 minus padding is clamped to 0, so the width is measured from the clamped edge: 110 + 6 - 0.
    expect(boxes).toEqual([{ x: 0, y: 14, w: 116, h: 32 }]);
  });
});
