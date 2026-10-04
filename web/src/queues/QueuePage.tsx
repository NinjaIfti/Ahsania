import { useParams } from "react-router";
import { useRecords } from "../api/hooks";
import type { Role } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { RecordList } from "../records/RecordList";

const QUEUES: Record<string, { status: string; title: string; roles: Role[] }> = {
  doctor: { status: "pending_doctor", title: "Waiting for doctor approval", roles: ["hospital_doctor"] },
  nsu: { status: "pending_nsu", title: "Waiting for NSU approval", roles: ["nsu_reviewer", "admin"] },
};

export default function QueuePage() {
  const { stage = "" } = useParams();
  const me = useCurrentUser();
  const queue = QUEUES[stage];
  const allowed = queue !== undefined && queue.roles.includes(me.role);
  const records = useRecords({ status: queue?.status }, allowed);

  if (!queue) return <p>Unknown queue.</p>;
  if (!allowed) return <p>This queue is not available for your role.</p>;
  const oldestFirst = [...(records.data ?? [])].sort((a, b) => a.updated_at.localeCompare(b.updated_at));
  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold">{queue.title}</h1>
      {records.isPending ? <p>Loading…</p> : <RecordList records={oldestFirst} empty="Nothing waiting." />}
    </section>
  );
}
