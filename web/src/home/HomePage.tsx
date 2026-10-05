import { Link, useLocation } from "react-router";
import { useRecords } from "../api/hooks";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";
import { useDeviceKey } from "../crypto/keyStore";
import { useOutbox } from "../outbox/OutboxContext";
import { RecordList } from "../records/RecordList";
import { card, secondaryButton } from "../ui/styles";

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
      {isHospital(me.role) ? <HospitalHome /> : <NsuHome />}
    </div>
  );
}

function HospitalHome() {
  const me = useCurrentUser();
  const deviceKey = useDeviceKey();
  const outbox = useOutbox();
  const drafts = useRecords({ status: "draft", mine: true });
  const reading = useRecords({ status: "processing", mine: true });
  const heldBack = useRecords({ status: "quarantined", mine: me.role === "uploader" });
  const doctorQueue = useRecords({ status: "pending_doctor" }, me.role === "hospital_doctor");
  const waiting = outbox.items.filter((item) => !item.failed);
  const refused = outbox.items.filter((item) => item.failed);

  return (
    <>
      <Link to="/capture" className="block rounded-xl bg-blue-700 p-6 text-center text-xl font-semibold text-white hover:bg-blue-800">
        New capture
      </Link>
      <p className="text-sm text-slate-600">
        {deviceKey.data ? (
          <>
            Device key <span className="font-mono">{deviceKey.data.fingerprint}</span>
          </>
        ) : me.role === "hospital_doctor" ? (
          <>
            This device has no hospital key — <Link to="/setup" className="underline">set it up</Link>.
          </>
        ) : (
          "This device has no hospital key — ask a hospital doctor to set it up."
        )}
      </p>
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
            Upload refused for {item.meta.study_code}: {item.error}
          </p>
          <button type="button" onClick={() => void outbox.discard(item.id)} className={`${secondaryButton} mt-2`}>
            Discard
          </button>
        </div>
      ))}
      {(heldBack.data?.length ?? 0) > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold text-red-800">Held back — possible patient details</h2>
          <RecordList records={heldBack.data ?? []} empty="" />
        </section>
      )}
      {me.role === "hospital_doctor" && (
        <Link to="/queue/doctor" className="block underline">
          {doctorQueue.data?.length ?? 0} waiting for doctor approval
        </Link>
      )}
      {(reading.data?.length ?? 0) > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Being read by the AI</h2>
          <RecordList records={reading.data ?? []} empty="" />
        </section>
      )}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">My drafts</h2>
        {drafts.isPending ? <p>Loading…</p> : <RecordList records={drafts.data ?? []} empty="No drafts." />}
      </section>
    </>
  );
}

function NsuHome() {
  const queue = useRecords({ status: "pending_nsu" });
  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-semibold">NSU review</h1>
      <Link to="/queue/nsu" className="underline">
        {queue.data?.length ?? 0} waiting for NSU approval
      </Link>
    </section>
  );
}
