import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import type { TemplateOut } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { useOutbox } from "../outbox/OutboxContext";
import { enqueue, flushOutbox, type SendResult } from "../outbox/outbox";
import type { OutboxMeta } from "../storage/idb";
import { PatientStep } from "./PatientStep";
import { PhotosStep } from "./PhotosStep";
import { TemplateStep } from "./TemplateStep";
import type { PageDraft } from "./types";

type Step = "patient" | "template" | "photos";
const STEP_LABEL: Record<Step, string> = { patient: "1. Patient", template: "2. Form", photos: "3. Photos" };

export default function CapturePage() {
  const me = useCurrentUser();
  const navigate = useNavigate();
  const outbox = useOutbox();
  const [step, setStep] = useState<Step>("patient");
  const [regNo, setRegNo] = useState<string | null>(null);
  const [template, setTemplate] = useState<TemplateOut | null>(null);
  const [pages, setPages] = useState<PageDraft[]>([]);
  const pagesRef = useRef(pages);

  useEffect(() => {
    pagesRef.current = pages;
  }, [pages]);
  useEffect(() => () => pagesRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  if (me.role !== "doctor") return <p>Only doctors can capture documents.</p>;

  async function uploadViaOutbox(meta: OutboxMeta) {
    const item = await enqueue(meta, pages.map((p) => p.blob), me.id);
    let result: SendResult | undefined = (await flushOutbox(me.id)).get(item.id);
    if (!result) result = (await flushOutbox(me.id)).get(item.id); // a flush that started earlier did not include it
    await outbox.refresh();
    if (result?.outcome === "done" && result.recordId) {
      navigate(`/records/${result.recordId}`);
    } else if (result?.outcome === "fail") {
      throw new Error(`Upload refused: ${result.error}. It is listed on the home screen.`);
    } else {
      navigate("/", { state: { notice: "Saved on this device — it will upload when the connection is back." } });
    }
  }

  return (
    <div className="space-y-4">
      <ol className="flex flex-wrap gap-3 text-sm">
        {(Object.keys(STEP_LABEL) as Step[]).map((s) => (
          <li key={s} className={s === step ? "font-semibold text-blue-700" : "text-slate-500"}>{STEP_LABEL[s]}</li>
        ))}
      </ol>
      {regNo && step !== "patient" && (
        <p className="text-sm">
          Patient <span className="font-mono">{regNo}</span>
          {template && step !== "template" ? ` · ${template.title}` : ""}
        </p>
      )}
      {step === "patient" && (
        <PatientStep
          initial={regNo ?? ""}
          onDone={(value) => {
            setRegNo(value);
            setStep("template");
          }}
        />
      )}
      {step === "template" && (
        <TemplateStep
          onBack={() => setStep("patient")}
          onDone={(t) => {
            setTemplate(t);
            setStep("photos");
          }}
        />
      )}
      {step === "photos" && regNo && template && (
        <PhotosStep
          pages={pages}
          onChange={setPages}
          onBack={() => setStep("template")}
          onUpload={(fillByHand) => uploadViaOutbox({ reg_no: regNo, template_key: template.key, fill_by_hand: fillByHand })}
        />
      )}
    </div>
  );
}
