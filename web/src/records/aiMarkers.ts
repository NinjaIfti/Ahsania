import type { AiColour, AiField, Extraction } from "../api/types";

/** What each spec §5.2 colour tells the person checking the form. */
export const AI_LABEL: Record<AiColour, string> = {
  green: "AI: found on the page",
  amber: "AI: please check",
  red: "AI: fails a check",
  grey: "AI: not in the document",
};

const isEmpty = (v: unknown) => v === null || v === undefined || (typeof v === "string" && v.trim() === "");

/** The AI's result for a field, as long as the field still holds what the AI filled in. */
export function aiMarker(extraction: Extraction | null | undefined, path: string, current: unknown): AiField | null {
  const field = extraction?.fields[path];
  if (!field || field.edited) return null;
  if ("value" in field && !(isEmpty(field.value) ? isEmpty(current) : field.value === current)) return null;
  return field;
}
