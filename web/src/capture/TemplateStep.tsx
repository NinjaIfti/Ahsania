import { useTemplates } from "../api/hooks";
import type { TemplateOut } from "../api/types";
import { secondaryButton } from "../ui/styles";

interface Props {
  onDone: (template: TemplateOut) => void;
  onBack: () => void;
}

export function TemplateStep({ onDone, onBack }: Props) {
  const templates = useTemplates();
  if (templates.isPending) return <p>Loading forms…</p>;
  if (templates.isError) return <p role="alert" className="text-red-700">{templates.error.message}</p>;
  const photographable = templates.data.filter((t) => t.kind !== "dicom");
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">What are you photographing?</h2>
      <div className="grid gap-2 sm:grid-cols-2">
        {photographable.map((t) => (
          <button
            key={t.key}
            type="button"
            disabled={t.locked}
            onClick={() => onDone(t)}
            className="min-h-16 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-teal-500 hover:bg-teal-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="block font-medium">{t.title}</span>
            {t.locked && <span className="text-sm text-slate-600">Locked until Phase 3</span>}
          </button>
        ))}
      </div>
      <button type="button" onClick={onBack} className={secondaryButton}>Back</button>
    </div>
  );
}
