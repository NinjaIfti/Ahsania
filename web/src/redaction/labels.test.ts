import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { hasEmail, hasLabel, hasMobile, hasNid, lineNeedsRedaction, suggestBoxes } from "./labels";

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

interface SharedCase {
  text: string;
  label: boolean;
  mobile: boolean;
  nid: boolean;
  email: boolean;
}

// The same cases the server's PHI safety net is tested against (server/tests/test_phi.py).
const CASES: SharedCase[] = JSON.parse(
  readFileSync(new URL("../../../server/tests/fixtures/phi_cases.json", import.meta.url), "utf8"),
);

describe("matches the server's PHI safety net", () => {
  it.each(CASES)("$text", (c) => {
    expect({ label: hasLabel(c.text), mobile: hasMobile(c.text), nid: hasNid(c.text), email: hasEmail(c.text) }).toEqual({
      label: c.label,
      mobile: c.mobile,
      nid: c.nid,
      email: c.email,
    });
    expect(lineNeedsRedaction(c.text)).toBe(c.label || c.mobile || c.nid || c.email);
  });
});
