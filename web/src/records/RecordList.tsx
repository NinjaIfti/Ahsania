import { Link } from "react-router";
import type { RecordSummary } from "../api/types";
import { ageLabel } from "../ui/time";

export function RecordList({ records, empty }: { records: RecordSummary[]; empty: string }) {
  if (records.length === 0) return <p className="text-slate-500">{empty}</p>;
  return (
    <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
      {records.map((r) => (
        <li key={r.id}>
          <Link to={`/records/${r.id}`} className="flex items-start justify-between gap-3 p-3 hover:bg-slate-50">
            <span>
              <span className="block font-medium">{r.template_title}</span>
              <span className="font-mono text-sm">{r.study_code}</span>
              <span className="text-sm text-slate-600"> · {r.document_date ?? "no date yet"}</span>
            </span>
            <span className="text-right text-sm text-slate-600">
              {r.status === "draft" && r.last_event?.action === "return" && (
                <span className="mb-1 inline-block rounded bg-amber-100 px-2 text-amber-800">Returned</span>
              )}
              {r.ai_amber > 0 && <span className="mb-1 ml-1 inline-block rounded bg-amber-100 px-2 text-amber-800">🟡 {r.ai_amber} to check</span>}
              {r.ai_red > 0 && <span className="mb-1 ml-1 inline-block rounded bg-red-100 px-2 text-red-800">🔴 {r.ai_red} failing</span>}
              <span className="block">{r.created_by_name}</span>
              <span className="block">{ageLabel(r.updated_at)}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
