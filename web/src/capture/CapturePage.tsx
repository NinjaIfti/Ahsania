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

type Step = "template" | "photos" | "patient";
const STEPS: Step[] = ["template", "photos", "patient"];
const STEP_LABEL: Record<Step, string> = { template: "Form", photos: "Photos", patient: "Patient ID" };

export default function CapturePage() {
  const me = useCurrentUser();
  const navigate = useNavigate();
  const outbox = useOutbox();
  const [step, setStep] = useState<Step>("template");
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
      <ol className="flex items-center gap-2 text-sm">
        {STEPS.map((s, i) => {
          const at = STEPS.indexOf(step);
          const tone = i < at ? "bg-teal-600 text-white" : i === at ? "bg-teal-700 text-white ring-4 ring-teal-100" : "bg-slate-200 text-slate-500";
          return (
            <li key={s} aria-current={s === step ? "step" : undefined} className="flex flex-1 items-center gap-2">
              <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold ${tone}`}>{i < at ? "✓" : i + 1}</span>
              <span className={s === step ? "font-semibold text-teal-800" : "text-slate-500"}>{STEP_LABEL[s]}</span>
              {i < STEPS.length - 1 && <span className="hidden h-px flex-1 bg-slate-300 sm:block" />}
            </li>
          );
        })}
      </ol>
      {template && step !== "template" && <p className="rounded-xl bg-teal-50 px-3 py-2 text-sm font-medium text-teal-900">{template.title}</p>}
      {step === "template" && (
        <TemplateStep
          onBack={() => navigate("/")}
          onDone={(t) => {
            setTemplate(t);
            setStep("photos");
          }}
        />
      )}
      {step === "photos" && template && (
        <PhotosStep pages={pages} onChange={setPages} onBack={() => setStep("template")} onNext={() => setStep("patient")} />
      )}
      {step === "patient" && template && (
        <PatientStep
          pages={pages}
          onBack={() => setStep("photos")}
          onUpload={(regNo, fillByHand) => uploadViaOutbox({ reg_no: regNo, template_key: template.key, fill_by_hand: fillByHand })}
        />
      )}
    </div>
  );
}
