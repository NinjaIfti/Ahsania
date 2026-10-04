import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import type { TemplateOut } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";
import { useDeviceKey } from "../crypto/keyStore";
import { PatientStep } from "./PatientStep";
import { PhotosStep } from "./PhotosStep";
import { TemplateStep } from "./TemplateStep";
import type { PageDraft } from "./types";

type Step = "patient" | "template" | "photos" | "redact";
const STEP_LABEL: Record<Step, string> = { patient: "1. Patient", template: "2. Form", photos: "3. Photos", redact: "4. Hide names" };

export default function CapturePage() {
  const me = useCurrentUser();
  const deviceKey = useDeviceKey();
  const [step, setStep] = useState<Step>("patient");
  const [studyCode, setStudyCode] = useState<string | null>(null);
  const [template, setTemplate] = useState<TemplateOut | null>(null);
  const [pages, setPages] = useState<PageDraft[]>([]);
  const pagesRef = useRef(pages);

  useEffect(() => {
    pagesRef.current = pages;
  }, [pages]);
  useEffect(() => () => pagesRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  if (!isHospital(me.role)) return <p>Only hospital staff can capture documents.</p>;
  if (deviceKey.isPending) return <p>Loading…</p>;
  if (!deviceKey.data) {
    return (
      <p>
        This device has no hospital key.{" "}
        {me.role === "hospital_doctor" ? <Link to="/setup" className="underline">Set it up</Link> : "Ask a hospital doctor to set it up."}
      </p>
    );
  }
  const key = deviceKey.data;

  return (
    <div className="space-y-4">
      <ol className="flex flex-wrap gap-3 text-sm">
        {(Object.keys(STEP_LABEL) as Step[]).map((s) => (
          <li key={s} className={s === step ? "font-semibold text-blue-700" : "text-slate-500"}>{STEP_LABEL[s]}</li>
        ))}
      </ol>
      {studyCode && step !== "patient" && (
        <p className="text-sm">
          Patient <span className="font-mono">{studyCode}</span>
          {template && step !== "template" ? ` · ${template.title}` : ""}
        </p>
      )}
      {step === "patient" && (
        <PatientStep
          cryptoKey={key.cryptoKey}
          onDone={(code) => {
            if (code !== studyCode) {
              pages.forEach((p) => URL.revokeObjectURL(p.url));
              setPages([]);
            }
            setStudyCode(code);
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
      {step === "photos" && <PhotosStep pages={pages} onChange={setPages} onBack={() => setStep("template")} onNext={() => setStep("redact")} />}
    </div>
  );
}
