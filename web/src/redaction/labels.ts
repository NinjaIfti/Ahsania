import type { Rect } from "../imaging/geometry";

/** Line labels that introduce patient identifiers (spec §4.3). */
export const REDACTION_LABELS = [
  "Name", "Patient", "Pt", "Mobile", "Mob", "Phone", "Cell", "Contact", "Address", "Addr",
  "Father", "Husband", "Guardian", "S/O", "D/O", "W/O", "Reg", "Registration", "ID", "MRN", "UHID", "NID",
];

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const ALTERNATION = REDACTION_LABELS.map(escape).join("|");
const STARTS_WITH_LABEL = new RegExp(`^\\s*(?:${ALTERNATION})(?![A-Za-z])`, "i");
const LABEL_THEN_COLON = new RegExp(`\\b(?:${ALTERNATION})\\b\\.?\\s*(?:No\\.?|Number)?\\s*:`, "i");
const BD_MOBILE = /(?:\+?88)?01[3-9]\d{8}/;

export interface OcrLine {
  text: string;
  bbox: { x0: number; y0: number; x1: number; y1: number };
}

export function lineNeedsRedaction(text: string): boolean {
  if (BD_MOBILE.test(text.replace(/[\s-]/g, ""))) return true;
  return STARTS_WITH_LABEL.test(text) || LABEL_THEN_COLON.test(text);
}

export function suggestBoxes(lines: OcrLine[], pad = 6): Rect[] {
  return lines
    .filter((line) => lineNeedsRedaction(line.text))
    .map(({ bbox }) => {
      const x = Math.max(0, bbox.x0 - pad);
      const y = Math.max(0, bbox.y0 - pad);
      return { x, y, w: bbox.x1 + pad - x, h: bbox.y1 + pad - y };
    });
}
