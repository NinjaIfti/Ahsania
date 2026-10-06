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

/** Mirrors capture.workflow.rules.can_delete: a doctor's own capture, until it has gone to the admin once. */
export function canDelete(
  me: { id: number; role: Role },
  r: { created_by_id: number; status: Status; sent_to_admin: boolean },
): boolean {
  return me.role === "doctor" && r.created_by_id === me.id && (r.status === "processing" || r.status === "draft") && !r.sent_to_admin;
}
