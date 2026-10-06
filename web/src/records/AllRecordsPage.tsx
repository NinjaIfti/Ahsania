import { useSearchParams } from "react-router";
import { useRecords } from "../api/hooks";
import type { Status } from "../api/types";
import { inputClass } from "../ui/styles";
import { STATUS_LABEL } from "../ui/StatusBadge";
import { RecordList } from "./RecordList";

export default function AllRecordsPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const mine = params.get("mine") === "1";
  const records = useRecords({ status: status || undefined, mine });
  return (
    <section className="space-y-3">
      <h1 className="text-xl font-bold text-slate-800">{mine ? "My records" : "All records"}</h1>
      <label className="block max-w-xs">
        <span className="text-sm font-medium">Show</span>
        <select value={status} onChange={(e) => setParams({ ...(e.target.value ? { status: e.target.value } : {}), ...(mine ? { mine: "1" } : {}) })} className={inputClass}>
          <option value="">All</option>
          {(Object.keys(STATUS_LABEL) as Status[]).map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
      </label>
      {records.isPending ? <p>Loading…</p> : <RecordList records={records.data ?? []} empty="No records." />}
    </section>
  );
}
