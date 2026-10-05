import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, json } from "../api/client";
import { useRecord } from "../api/hooks";
import type { EventOut, RecordDetail, SourceBox } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";
import { StatusBadge } from "../ui/StatusBadge";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";
import { useNow } from "../ui/useNow";
import { FormRenderer } from "./FormRenderer";
import { PageViewer, type PageMark } from "./PageViewer";
import { availableActions, canEdit, fillByHandOffered, type UiAction } from "./permissions";

/** The server's 409 for a stale row_version. Any other 409 carries its own reason, which is shown as it is. */
const CONFLICT = "Someone else changed this record — reload";

const DONE: Record<UiAction, string> = {
  submit: "Submitted for doctor review",
  approve: "Approved",
  return: "Returned to the uploader",
  reopen: "Reopened",
  fill_by_hand: "The AI was stopped — fill the form in by hand",
  release: "Released — the AI is reading it again",
};

const EVENT_LABEL: Record<string, string> = {
  upload: "uploaded",
  edit: "edited",
  submit: "submitted",
  approve: "approved",
  return: "returned",
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
  const now = useNow(5_000);
  const [values, setValues] = useState(r.values);
  const [syncedVersion, setSyncedVersion] = useState(r.row_version);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [dialog, setDialog] = useState<"return" | "reopen" | "release" | null>(null);
  const [comment, setComment] = useState("");
  const [sources, setSources] = useState<SourceBox[]>([]);

  // When the server copy changes (save, action, the AI finishing, reload), show its values.
  if (syncedVersion !== r.row_version) {
    setSyncedVersion(r.row_version);
    setValues(r.values);
  }

  const editable = canEdit(me.role, r.status);
  const dirty = JSON.stringify(values) !== JSON.stringify(r.values);
  // A record whose photos expired cannot be released: there is nothing left for the AI to read.
  const actions = availableActions(me.role, r.status, r.created_by_id === me.id).filter(
    (a) => a !== "release" || !r.quarantine?.files_expired,
  );
  const errors = Object.fromEntries(r.errors.map((e) => [e.path, e.message]));
  const lastReturn = r.status === "draft" ? [...r.events].reverse().find((e) => e.action === "return" || e.action === "reopen") : undefined;
  const marks: PageMark[] =
    r.status === "quarantined" && r.quarantine
      ? r.quarantine.hits.map((h) => ({ page: h.page, box: h.box, tone: "hit" as const }))
      : sources.map((s) => ({ ...s, tone: "source" as const }));

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
            Study code <span className="font-mono">{r.study_code}</span>
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
          Returned by {lastReturn.actor_name}: {lastReturn.comment}
        </p>
      )}
      {r.status === "processing" && (
        <div className="space-y-2 rounded-md bg-slate-100 p-3">
          <p>The AI is reading this document…</p>
          {fillByHandOffered(me.role, r.status, r.extraction_queued_at, now) && (
            <>
              <p className="text-sm text-slate-600">This is taking longer than usual.</p>
              <button type="button" disabled={busy} onClick={() => run("fill_by_hand")} className={secondaryButton}>
                Fill by hand now
              </button>
            </>
          )}
        </div>
      )}
      {r.status === "draft" && r.extraction_status === "failed" && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">The AI could not read this document — fill the form in by hand.</p>
      )}
      {r.status === "draft" && r.extraction && (
        <p className="text-sm text-slate-600">The AI filled in this form. Check every amber field; tap a field to see where it was read on the page.</p>
      )}
      {r.status === "quarantined" && r.quarantine && (
        <div role="alert" className="space-y-2 rounded-md bg-red-50 p-3 text-red-900">
          <p className="font-medium">Held back. {r.quarantine.summary}.</p>
          <p className="text-sm">
            Nothing has been shared with NSU.{" "}
            {r.quarantine.files_expired
              ? "The photos were deleted after 14 days — upload them again."
              : "The red outlines show where the details were found."}
          </p>
          {isHospital(me.role) && (
            <Link to={`/records/${r.id}/reupload`} className={`${primaryButton} inline-block`}>
              Upload new photos
            </Link>
          )}
        </div>
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
                Submit for doctor review
              </button>
            )}
            {actions.includes("approve") && (
              <button type="button" disabled={busy} onClick={() => run("approve")} className={primaryButton}>
                Approve
              </button>
            )}
            {actions.includes("return") && (
              <button type="button" disabled={busy} onClick={() => setDialog("return")} className={secondaryButton}>
                Return…
              </button>
            )}
            {actions.includes("reopen") && (
              <button type="button" disabled={busy} onClick={() => setDialog("reopen")} className={secondaryButton}>
                Reopen…
              </button>
            )}
            {actions.includes("release") && (
              <button type="button" disabled={busy} onClick={() => setDialog("release")} className={secondaryButton}>
                Release — false alarm…
              </button>
            )}
          </div>
          {me.role === "hospital_doctor" && r.status === "pending_doctor" && r.created_by_id === me.id && (
            <p className="text-sm text-slate-600">You uploaded this record, so another doctor must approve it.</p>
          )}
          {dialog && (
            <div className={`${card} space-y-2`}>
              <label className="block text-sm font-medium">
                {dialog === "return" ? "What needs fixing?" : dialog === "reopen" ? "Reason for reopening" : "Why is this a false alarm?"}
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
