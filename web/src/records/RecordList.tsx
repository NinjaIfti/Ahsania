import { Link } from "react-router";
import type { RecordSummary } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { StatusBadge } from "../ui/StatusBadge";
import { ageLabel } from "../ui/time";
import { DeleteButton } from "./DeleteButton";
import { canDelete } from "./permissions";

/** The card's left edge: red/amber when something needs a look, otherwise the status colour. */
function edge(r: RecordSummary): string {
  if (r.ai_red > 0) return "border-l-red-500";
  if (r.ai_amber > 0 || (r.status === "draft" && r.sent_to_admin)) return "border-l-amber-400";
  if (r.status === "approved") return "border-l-green-600";
  if (r.status === "pending_admin") return "border-l-cyan-500";
  if (r.status === "processing") return "border-l-slate-300";
  return "border-l-teal-600";
}

export function RecordList({ records, empty }: { records: RecordSummary[]; empty: string }) {
  const me = useCurrentUser();
  if (records.length === 0) return <p className="rounded-2xl bg-white p-4 text-center text-slate-500 shadow-sm">{empty}</p>;
  return (
    <ul className="space-y-2">
      {records.map((r) => (
        <li key={r.id} className={`rounded-2xl border border-l-4 border-slate-200 bg-white shadow-sm ${edge(r)}`}>
          <Link to={`/records/${r.id}`} className="block rounded-2xl p-3 hover:bg-slate-50">
            <span className="flex items-start justify-between gap-2">
              <span className="font-semibold">{r.template_title}</span>
              <span className="shrink-0 text-xs text-slate-500">{ageLabel(r.updated_at)}</span>
            </span>
            <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span className="font-mono">{r.reg_no}</span>
              <StatusBadge status={r.status} />
              {r.status === "draft" && r.last_event?.action === "return" && (
                <span className="rounded-full bg-amber-100 px-2 text-xs font-semibold text-amber-800">Sent back</span>
              )}
              {r.ai_amber > 0 && <span className="rounded-full bg-amber-100 px-2 text-xs font-semibold text-amber-800">🟡 {r.ai_amber} to check</span>}
              {r.ai_red > 0 && <span className="rounded-full bg-red-100 px-2 text-xs font-semibold text-red-800">🔴 {r.ai_red} failing</span>}
            </span>
            <span className="mt-1 block text-xs text-slate-500">
              {r.created_by_name} · {r.document_date ?? "no date yet"}
            </span>
          </Link>
          {canDelete(me, r) && (
            <div className="flex justify-end border-t border-slate-100 px-2 py-1">
              <DeleteButton recordId={r.id} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
