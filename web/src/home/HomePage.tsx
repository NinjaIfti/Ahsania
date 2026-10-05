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
        <p role="status" className="rounded-md bg-sky-50 p-3 text-sky-900">
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
  const waiting = outbox.items.filter((item) => !item.failed);
  const refused = outbox.items.filter((item) => item.failed);
  const sentBack = (drafts.data ?? []).filter((r) => SENT_BACK.has(r.last_event?.action ?? ""));
  const otherDrafts = (drafts.data ?? []).filter((r) => !SENT_BACK.has(r.last_event?.action ?? ""));

  return (
    <>
      <Link to="/capture" className="block rounded-xl bg-blue-700 p-6 text-center text-xl font-semibold text-white hover:bg-blue-800">
        New capture
      </Link>
      {waiting.length > 0 && (
        <div className={card}>
          <p>{waiting.length} waiting to upload</p>
          <button type="button" onClick={() => void outbox.flush()} className={`${secondaryButton} mt-2`}>
            Try now
          </button>
        </div>
      )}
      {outbox.othersWaiting > 0 && (
        <p className="text-sm text-slate-600">{outbox.othersWaiting} waiting for another user to sign in on this device</p>
      )}
      {refused.map((item) => (
        <div key={item.id} className="rounded-md bg-red-50 p-3 text-red-900">
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
          <h2 className="text-lg font-semibold text-amber-800">Sent back to me</h2>
          <RecordList records={sentBack} empty="" />
        </section>
      )}
      {(reading.data?.length ?? 0) > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Being read by the AI</h2>
          <RecordList records={reading.data ?? []} empty="" />
        </section>
      )}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">My drafts</h2>
        {drafts.isPending ? <p>Loading…</p> : <RecordList records={otherDrafts} empty="No drafts." />}
      </section>
      <Link to="/records?status=pending_admin" className="block underline">
        {waitingForAdmin.data?.length ?? 0} of mine waiting for admin
      </Link>
    </>
  );
}

function AdminHome() {
  const queue = useRecords({ status: "pending_admin" });
  const oldestFirst = [...(queue.data ?? [])].sort((a, b) => a.updated_at.localeCompare(b.updated_at));
  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-semibold">Waiting for admin</h1>
      {queue.isPending ? <p>Loading…</p> : <RecordList records={oldestFirst} empty="Nothing waiting." />}
    </section>
  );
}
