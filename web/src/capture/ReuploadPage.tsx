import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import { useRecord } from "../api/hooks";
import type { RecordDetail } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";
import { useDeviceKey } from "../crypto/keyStore";
import { PhotosStep } from "./PhotosStep";
import { RedactStep } from "./RedactStep";
import type { PageDraft } from "./types";

/** New redacted photos for a record the safety net held back (spec §8.1). Sent while online; there is no outbox. */
export default function ReuploadPage() {
  const { id = "" } = useParams();
  const me = useCurrentUser();
  const record = useRecord(id);
  const deviceKey = useDeviceKey();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [step, setStep] = useState<"photos" | "redact">("photos");
  const [pages, setPages] = useState<PageDraft[]>([]);
  const pagesRef = useRef(pages);

  useEffect(() => {
    pagesRef.current = pages;
  }, [pages]);
  useEffect(() => () => pagesRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  if (!isHospital(me.role)) return <p>Only hospital staff can upload photos.</p>;
  if (record.isPending || deviceKey.isPending) return <p>Loading…</p>;
  if (record.isError) return <p role="alert" className="text-red-700">{record.error.message}</p>;
  const r = record.data;
  if (r.status !== "quarantined") {
    return (
      <p>
        This record is not held back. <Link to={`/records/${r.id}`} className="underline">Back to the record</Link>
      </p>
    );
  }
  if (!deviceKey.data) {
    return (
      <p>
        This device has no hospital key.{" "}
        {me.role === "hospital_doctor" ? <Link to="/setup" className="underline">Set it up</Link> : "Ask a hospital doctor to set it up."}
      </p>
    );
  }
  const fingerprint = deviceKey.data.fingerprint;

  async function send(redacted: Blob[]) {
    const form = new FormData();
    form.append("meta", JSON.stringify({ row_version: r.row_version, key_fingerprint: fingerprint }));
    redacted.forEach((blob, i) => form.append("pages", blob, `page-${i + 1}.jpg`));
    const updated = await api<RecordDetail>(`/records/${r.id}/reupload`, { method: "POST", body: form });
    queryClient.setQueryData(["record", updated.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["records"] });
    navigate(`/records/${updated.id}`);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">New photos for {r.template_title}</h1>
      <p className="text-sm">
        Patient <span className="font-mono">{r.study_code}</span> · {r.quarantine?.summary}
      </p>
      {step === "photos" && <PhotosStep pages={pages} onChange={setPages} onBack={() => navigate(`/records/${r.id}`)} onNext={() => setStep("redact")} />}
      {step === "redact" && <RedactStep pages={pages} onChange={setPages} onBack={() => setStep("photos")} onUpload={send} />}
    </div>
  );
}
