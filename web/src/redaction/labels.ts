import type { Rect } from "../imaging/geometry";

/** Line labels that introduce patient identifiers (spec §4.3). */
export const REDACTION_LABELS = [
  "Name", "Patient", "Pt", "Mobile", "Mob", "Phone", "Cell", "Contact", "Address", "Addr",
  "Father", "Husband", "Guardian", "S/O", "D/O", "W/O", "Reg", "Registration", "ID", "MRN", "UHID", "NID",
];
/** Labels that introduce an identifier anywhere in a line. The others also occur in clinical prose. */
export const MIDLINE_LABELS = [
  "Name", "Father", "Husband", "Guardian", "Mobile", "Phone", "Address",
  "Registration", "MRN", "UHID", "NID", "S/O", "D/O", "W/O",
];

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();

function alternation(labels: string[], anyCase = false): string {
  const variants = new Set(labels.flatMap((l) => (anyCase ? [l, l.toUpperCase(), l.toLowerCase(), capitalize(l)] : [l])));
  return [...variants].sort((a, b) => b.length - a.length).map(escape).join("|");
}

// The same three rules as server/capture/extraction/phi.py; both are tested against server/tests/fixtures/phi_cases.json.
const ALL = alternation(REDACTION_LABELS);
const AT_START = new RegExp(`^[^A-Za-z0-9]*(?:${ALL})(?![A-Za-z])`, "i");
const WITH_COLON = new RegExp(`(?<![A-Za-z])(?:${ALL})(?:'s)?\\.?\\s*(?:(?:No|Number|Name)\\.?\\s*)?[:#]`, "i");
const MIDLINE = new RegExp(`(?<![A-Za-z])(?:${alternation(MIDLINE_LABELS, true)})\\s+(?=[A-Z0-9])`);

const BENGALI_ZERO = 0x09e6;
const toAsciiDigits = (s: string) => s.replace(/[০-৯]/g, (d) => String(d.charCodeAt(0) - BENGALI_ZERO));
const DIGIT_SEPARATORS = /(?<=\d)[\s\-.()]{1,3}(?=\d)/g;
const BD_MOBILE = /(?<!\d)(?:\+?88)?01[3-9]\d{8}(?!\d)/;
const NID = /(?<![\d.,])(?:\d{17}|\d{13}|\d{10})(?!\d|[.,]\d)/;
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/;

export const hasLabel = (text: string): boolean => AT_START.test(text) || WITH_COLON.test(text) || MIDLINE.test(text);
export const hasMobile = (text: string): boolean => BD_MOBILE.test(toAsciiDigits(text).replace(DIGIT_SEPARATORS, ""));
export const hasNid = (text: string): boolean => NID.test(toAsciiDigits(text));
export const hasEmail = (text: string): boolean => EMAIL.test(text);

export interface OcrLine {
  text: string;
  bbox: { x0: number; y0: number; x1: number; y1: number };
}

export function lineNeedsRedaction(text: string): boolean {
  return hasLabel(text) || hasMobile(text) || hasNid(text) || hasEmail(text);
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
