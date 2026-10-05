import type { Role, Status } from "../api/types";
import { isHospital } from "../auth/roles";

/** Mirrors capture.workflow.rules.can_edit on the server. */
export function canEdit(role: Role, status: Status): boolean {
  if (role === "uploader") return status === "draft";
  if (role === "hospital_doctor") return status === "draft" || status === "pending_doctor";
  return false;
}

export type UiAction = "submit" | "approve" | "return" | "reopen" | "fill_by_hand";

export function availableActions(role: Role, status: Status, isCreator: boolean): UiAction[] {
  if (status === "draft" && isHospital(role)) return ["submit"];
  if (status === "pending_doctor" && role === "hospital_doctor") return isCreator ? ["return"] : ["approve", "return"];
  if (status === "pending_nsu" && role === "nsu_reviewer") return ["approve", "return"];
  if (status === "approved" && role === "admin") return ["reopen"];
  return [];
}

/** Spec §11.2: after 2 minutes of waiting for the AI, hospital staff may fill the form in by hand. */
export const FILL_BY_HAND_AFTER_MS = 2 * 60_000;

export function fillByHandOffered(role: Role, status: Status, queuedAt: string | null, now: number): boolean {
  if (!isHospital(role) || status !== "processing" || queuedAt === null) return false;
  return now - Date.parse(queuedAt) >= FILL_BY_HAND_AFTER_MS;
}
