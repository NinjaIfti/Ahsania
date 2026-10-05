import type { Status } from "../api/types";

export const STATUS_LABEL: Record<Status, string> = {
  processing: "Being read by AI",
  draft: "Draft",
  pending_admin: "Waiting for admin",
  approved: "Approved",
};

const COLOUR: Record<Status, string> = {
  processing: "bg-slate-100 text-slate-700",
  draft: "bg-slate-100 text-slate-800",
  pending_admin: "bg-amber-100 text-amber-800",
  approved: "bg-green-100 text-green-800",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span data-testid="record-status" className={`rounded px-2 py-0.5 text-sm font-medium ${COLOUR[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}
