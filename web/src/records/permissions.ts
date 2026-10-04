import type { Role, Status } from "../api/types";
import { isHospital } from "../auth/roles";

/** Mirrors capture.workflow.rules.can_edit on the server. */
export function canEdit(role: Role, status: Status): boolean {
  if (role === "uploader") return status === "draft";
  if (role === "hospital_doctor") return status === "draft" || status === "pending_doctor";
  return false;
}

export type UiAction = "submit" | "approve" | "return" | "reopen";

export function availableActions(role: Role, status: Status, isCreator: boolean): UiAction[] {
  if (status === "draft" && isHospital(role)) return ["submit"];
  if (status === "pending_doctor" && role === "hospital_doctor") return isCreator ? ["return"] : ["approve", "return"];
  if (status === "pending_nsu" && role === "nsu_reviewer") return ["approve", "return"];
  if (status === "approved" && role === "admin") return ["reopen"];
  return [];
}
