import type { Role, Status } from "../api/types";

/** Mirrors capture.workflow.rules.can_edit on the server. */
export function canEdit(role: Role, status: Status): boolean {
  return role === "doctor" && status === "draft";
}

export type UiAction = "submit" | "approve" | "return" | "reopen" | "fill_by_hand";

export function availableActions(role: Role, status: Status): UiAction[] {
  if (role === "doctor" && status === "draft") return ["submit"];
  if (role === "doctor" && status === "processing") return ["fill_by_hand"];
  if (role === "admin" && status === "pending_admin") return ["approve", "return"];
  if (role === "admin" && status === "approved") return ["reopen"];
  return [];
}
