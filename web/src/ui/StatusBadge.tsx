import type { Status } from "../api/types";

export const STATUS_LABEL: Record<Status, string> = {
  processing: "Being read by AI",
  draft: "Draft",
  pending_admin: "Waiting for admin",
  approved: "Approved",
};

const COLOUR: Record<Status, string> = {
  processing: "bg-slate-100 text-slate-700",
  draft: "bg-teal-100 text-teal-800",
  pending_admin: "bg-cyan-100 text-cyan-800",
  approved: "bg-green-100 text-green-800",
};

/** `main` marks the record page's own badge (tests look it up); list badges leave it off. */
export function StatusBadge({ status, main = false }: { status: Status; main?: boolean }) {
  return (
    <span data-testid={main ? "record-status" : undefined} className={`rounded-full px-2 py-0.5 text-xs font-semibold ${COLOUR[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}
