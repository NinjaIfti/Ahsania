import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, api, json } from "../api/client";
import { useRecord } from "../api/hooks";
import type { EventOut, RecordDetail, SourceBox } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { StatusBadge } from "../ui/StatusBadge";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";
import { FormRenderer } from "./FormRenderer";
import { PageViewer, type PageMark } from "./PageViewer";
import { DeleteButton } from "./DeleteButton";
import { availableActions, canDelete, canEdit, type UiAction } from "./permissions";

/** The server's 409 for a stale row_version. Any other 409 carries its own reason, which is shown as it is. */
const CONFLICT = "Someone else changed this record — reload";

const DONE: Record<UiAction, string> = {
  submit: "Sent to the admin",
  approve: "Approved",
  return: "Sent back to the doctor",
  reopen: "Reopened",
  fill_by_hand: "The AI was stopped — fill the form in by hand",
};

const EVENT_LABEL: Record<string, string> = {
  upload: "uploaded",
  edit: "edited",
  submit: "approved it and sent it to the admin",
  approve: "approved",
  return: "sent it back",
  reopen: "reopened",
  quarantine: "held it back",
  release: "released it",
  reupload: "uploaded new photos",
  fill_by_hand: "chose to fill it in by hand",
};

export default function RecordPage() {
  const { id = "" } = useParams();
  const record = useRecord(id);
  if (record.isPending) return <p>Loading…</p>;
  if (record.isError) return <p role="alert" className="text-red-700">{record.error.message}</p>;
  return <RecordView key={record.data.id} record={record.data} />;
}

function RecordView({ record: r }: { record: RecordDetail }) {
  const me = useCurrentUser();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [values, setValues] = useState(r.values);
  const [syncedVersion, setSyncedVersion] = useState(r.row_version);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [dialog, setDialog] = useState<"return" | "reopen" | null>(null);
  const [comment, setComment] = useState("");
  const [sources, setSources] = useState<SourceBox[]>([]);

  // When the server copy changes (save, action, the AI finishing, reload), show its values.
  if (syncedVersion !== r.row_version) {
    setSyncedVersion(r.row_version);
    setValues(r.values);
  }

  const editable = canEdit(me.role, r.status);
  const dirty = JSON.stringify(values) !== JSON.stringify(r.values);
  const actions = availableActions(me.role, r.status);
  const errors = Object.fromEntries(r.errors.map((e) => [e.path, e.message]));
  const lastReturn = r.status === "draft" ? [...r.events].reverse().find((e) => e.action === "return" || e.action === "reopen") : undefined;
  const marks: PageMark[] = sources.map((s) => ({ ...s, tone: "source" as const }));

  function store(updated: RecordDetail) {
    queryClient.setQueryData(["record", updated.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["records"] });
  }

  function failed(e: unknown, fallback: string) {
    if (e instanceof ApiError && e.status === 409 && e.message === CONFLICT) setConflict(true);
    else setMessage(e instanceof Error ? e.message : fallback);
  }

  /** Saves the form; returns the updated record, or null after showing the error. */
  async function save(): Promise<RecordDetail | null> {
    try {
      const updated = await api<RecordDetail>(`/records/${r.id}/values`, { method: "PATCH", body: json({ row_version: r.row_version, values }) });
      store(updated);
      return updated;
    } catch (e) {
      failed(e, "Save failed");
      return null;
    }
  }

  async function onSave() {
    setBusy(true);
    setMessage(null);
    if (await save()) setMessage("Saved");
    setBusy(false);
  }

  async function run(action: UiAction, withComment?: string) {
    setBusy(true);
    setMessage(null);
    try {
      // Unsaved edits are saved first; the action then names the row_version it was taken on.
      let current = r;
      if (editable && dirty) {
        const saved = await save();
        if (!saved) return;
        current = saved;
      }
      store(
        await api<RecordDetail>(`/records/${r.id}/transition`, {
          method: "POST",
          body: json({ action, comment: withComment ?? null, row_version: current.row_version }),
        }),
      );
      setDialog(null);
      setComment("");
      setMessage(DONE[action]);
    } catch (e) {
      failed(e, "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">{r.template_title}</h1>
        <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
          <span>
            Patient ID <span className="font-mono">{r.reg_no}</span>
          </span>
          <StatusBadge status={r.status} />
          <span>Uploaded by {r.created_by_name}</span>
        </p>
      </header>

      {r.duplicate_of.length > 0 && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">
          This looks already uploaded for this patient:
          {r.duplicate_of.map((d) => (
            <Link key={d} to={`/records/${d}`} className="ml-2 underline">
              {d.slice(0, 8)}
            </Link>
          ))}
        </p>
      )}
      {lastReturn && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">
          {lastReturn.action === "reopen" ? "Reopened" : "Sent back"} by {lastReturn.actor_name}: {lastReturn.comment}
        </p>
      )}
      {r.status === "processing" && (
        <div className="space-y-2 rounded-md bg-slate-100 p-3">
          <p>The AI is reading this document…</p>
          {actions.includes("fill_by_hand") && (
            <button type="button" disabled={busy} onClick={() => run("fill_by_hand")} className={secondaryButton}>
              Fill by hand now
            </button>
          )}
        </div>
      )}
      {r.status === "draft" && r.extraction_status === "failed" && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">The AI could not read this document — fill the form in by hand.</p>
      )}
      {r.status === "draft" && r.extraction && (
        <p className="text-sm text-slate-600">The AI filled in this form. Check every amber field; tap a field to see where it was read on the page.</p>
      )}
      {conflict && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-red-800">
          {CONFLICT}
          <button
            type="button"
            className={`${secondaryButton} ml-2`}
            onClick={() => {
              setConflict(false);
              void queryClient.invalidateQueries({ queryKey: ["record", r.id] });
            }}
          >
            Reload
          </button>
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <PageViewer files={r.files} marks={marks} />
        <div className="space-y-4">
          <FormRenderer
            fields={r.template.definition.fields}
            values={values}
            onChange={setValues}
            errors={errors}
            readOnly={!editable}
            flags={lastReturn?.field_flags ?? {}}
            extraction={r.extraction}
            onFieldFocus={(_, ai) => setSources(ai?.sources ?? [])}
          />
          <div className="flex flex-wrap gap-2">
            {editable && (
              <button type="button" disabled={busy || !dirty} onClick={onSave} className={secondaryButton}>
                Save
              </button>
            )}
            {actions.includes("submit") && (
              <button type="button" disabled={busy} onClick={() => run("submit")} className={primaryButton}>
                Approve and send to admin
              </button>
            )}
            {actions.includes("approve") && (
              <button type="button" disabled={busy} onClick={() => run("approve")} className={primaryButton}>
                Approve
              </button>
            )}
            {actions.includes("return") && (
              <button type="button" disabled={busy} onClick={() => setDialog("return")} className={secondaryButton}>
                Send back…
              </button>
            )}
            {actions.includes("reopen") && (
              <button type="button" disabled={busy} onClick={() => setDialog("reopen")} className={secondaryButton}>
                Reopen…
              </button>
            )}
            {canDelete(me, r) && <DeleteButton recordId={r.id} onDeleted={() => navigate("/", { state: { notice: "Capture deleted." } })} />}
          </div>
          {dialog && (
            <div className={`${card} space-y-2`}>
              <label className="block text-sm font-medium">
                {dialog === "return" ? "What needs fixing?" : "Reason for reopening"}
                <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} className={inputClass} />
              </label>
              <div className="flex gap-2">
                <button type="button" disabled={busy || !comment.trim()} onClick={() => run(dialog, comment)} className={primaryButton}>
                  Confirm
                </button>
                <button type="button" onClick={() => setDialog(null)} className={secondaryButton}>
                  Cancel
                </button>
              </div>
            </div>
          )}
          {message && (
            <p role="status" className="text-sm">
              {message}
            </p>
          )}
        </div>
      </div>
      <History events={r.events} />
    </div>
  );
}

function History({ events }: { events: EventOut[] }) {
  return (
    <section className={card}>
      <h2 className="mb-2 font-semibold">History</h2>
      <ol className="space-y-1 text-sm">
        {events.map((e) => (
          <li key={e.id}>
            {new Date(e.created_at).toLocaleString()} — {e.actor_name} {EVENT_LABEL[e.action] ?? e.action}
            {e.action === "edit" && e.field_changes ? ` ${e.field_changes.length} field(s)` : ""}
            {e.comment ? `: ${e.comment}` : ""}
          </li>
        ))}
      </ol>
    </section>
  );
}
