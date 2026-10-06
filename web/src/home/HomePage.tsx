import { Link, useLocation } from "react-router";
import { useRecords } from "../api/hooks";
import { useCurrentUser } from "../auth/RequireAuth";
import { useOutbox } from "../outbox/OutboxContext";
import { RecordList } from "../records/RecordList";
import { card, secondaryButton } from "../ui/styles";

const SENT_BACK = new Set(["return", "reopen"]);

export default function HomePage() {
  const me = useCurrentUser();
  const location = useLocation();
  const notice = (location.state as { notice?: string } | null)?.notice;
  return (
    <div className="space-y-6">
      {notice && (
        <p role="status" className="rounded-xl bg-teal-50 p-3 text-teal-900">
          {notice}
        </p>
      )}
      {me.role === "doctor" ? <DoctorHome /> : <AdminHome />}
    </div>
  );
}

function DoctorHome() {
  const outbox = useOutbox();
  const drafts = useRecords({ status: "draft", mine: true });
  const reading = useRecords({ status: "processing", mine: true });
  const waitingForAdmin = useRecords({ status: "pending_admin", mine: true });
  const approved = useRecords({ status: "approved", mine: true });
  const waiting = outbox.items.filter((item) => !item.failed);
  const refused = outbox.items.filter((item) => item.failed);
  const sentBack = (drafts.data ?? []).filter((r) => SENT_BACK.has(r.last_event?.action ?? ""));
  const otherDrafts = (drafts.data ?? []).filter((r) => !SENT_BACK.has(r.last_event?.action ?? ""));

  return (
    <>
      <Link
        to="/capture"
        aria-label="New capture"
        className="block rounded-2xl bg-white p-5 text-center shadow-lg shadow-teal-900/10 ring-1 ring-teal-100 hover:ring-teal-300"
      >
        <span aria-hidden="true" className="mx-auto mb-2 grid h-14 w-14 place-items-center rounded-full bg-teal-100 text-2xl">
          📷
        </span>
        <span className="block text-lg font-bold text-teal-800">New capture</span>
        <span className="block text-sm text-slate-500">Form → Photos → Patient ID</span>
      </Link>
      <nav aria-label="My records" className="flex flex-wrap gap-2 text-sm">
        <CountChip to="/records?status=draft&mine=1" label="Drafts" count={drafts.data?.length} />
        <CountChip to="/records?status=pending_admin&mine=1" label="With admin" count={waitingForAdmin.data?.length} />
        <CountChip to="/records?status=approved&mine=1" label="Done" count={approved.data?.length} />
      </nav>
      {waiting.length > 0 && (
        <div className={`${card} border-amber-200 bg-amber-50`}>
          <p className="font-medium text-amber-900">{waiting.length} waiting to upload</p>
          <button type="button" onClick={() => void outbox.flush()} className={`${secondaryButton} mt-2`}>
            Try now
          </button>
        </div>
      )}
      {outbox.othersWaiting > 0 && (
        <p className="text-sm text-slate-600">{outbox.othersWaiting} waiting for another user to sign in on this device</p>
      )}
      {refused.map((item) => (
        <div key={item.id} className="rounded-xl bg-red-50 p-3 text-red-900">
          <p>
            Upload refused for {item.meta.reg_no ?? "an earlier capture"}: {item.error}
          </p>
          <button type="button" onClick={() => void outbox.discard(item.id)} className={`${secondaryButton} mt-2`}>
            Discard
          </button>
        </div>
      ))}
      {sentBack.length > 0 && (
        <section className="space-y-2">
          <h2 className="font-semibold text-amber-800">Sent back to me</h2>
          <RecordList records={sentBack} empty="" />
        </section>
      )}
      {(reading.data?.length ?? 0) > 0 && (
        <section className="space-y-2">
          <h2 className="font-semibold text-slate-800">Being read by the AI</h2>
          <RecordList records={reading.data ?? []} empty="" />
        </section>
      )}
      <section className="space-y-2">
        <h2 className="font-semibold text-slate-800">My drafts</h2>
        {drafts.isPending ? <p>Loading…</p> : <RecordList records={otherDrafts} empty="No drafts." />}
      </section>
    </>
  );
}

function AdminHome() {
  const queue = useRecords({ status: "pending_admin" });
  const oldestFirst = [...(queue.data ?? [])].sort((a, b) => a.updated_at.localeCompare(b.updated_at));
  return (
    <section className="space-y-2">
      <h1 className="text-xl font-bold text-slate-800">Waiting for admin</h1>
      {queue.isPending ? <p>Loading…</p> : <RecordList records={oldestFirst} empty="Nothing waiting." />}
    </section>
  );
}

function CountChip({ to, label, count }: { to: string; label: string; count: number | undefined }) {
  return (
    <Link to={to} className="rounded-full border border-teal-200 bg-white px-3 py-1.5 font-medium text-teal-800 hover:bg-teal-50">
      {label} <span className="font-bold">{count ?? "…"}</span>
    </Link>
  );
}
