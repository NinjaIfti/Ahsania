import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import type { Rect } from "../imaging/geometry";
import { useCurrentUser } from "../auth/RequireAuth";
import { burnRedactions } from "../imaging/render";
import { useOutbox } from "../outbox/OutboxContext";
import { enqueue, flushOutbox, type SendResult } from "../outbox/outbox";
import { suggestBoxes } from "../redaction/labels";
import { ocrLines } from "../redaction/ocr";
import type { OutboxMeta } from "../storage/idb";
import { primaryButton, secondaryButton } from "../ui/styles";
import { RedactionCanvas } from "./RedactionCanvas";
import type { PageDraft } from "./types";

interface Props {
  pages: PageDraft[];
  onChange: (pages: PageDraft[]) => void;
  meta: OutboxMeta;
  onBack: () => void;
}

export function RedactStep({ pages, onChange, meta, onBack }: Props) {
  const navigate = useNavigate();
  const outbox = useOutbox();
  const me = useCurrentUser();
  const [index, setIndex] = useState(0);
  const [seen, setSeen] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<number | null>(null);
  const [ocrBusy, setOcrBusy] = useState(() => pages.some((p) => !p.ocrDone));
  const [ocrWarning, setOcrWarning] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Suggest boxes once per page, on this device only. Editing is disabled until this finishes.
  useEffect(() => {
    const pending = pages.filter((p) => !p.ocrDone);
    if (pending.length === 0) return;
    let cancelled = false;
    void (async () => {
      let next = pages;
      for (const page of pending) {
        let found: Rect[] = [];
        try {
          found = suggestBoxes(await ocrLines(page.blob));
        } catch {
          setOcrWarning("Automatic name finding failed — draw the boxes by hand.");
        }
        if (cancelled) return;
        next = next.map((p) => (p.id === page.id ? { ...p, boxes: [...p.boxes, ...found], ocrDone: true } : p));
      }
      onChange(next);
      setOcrBusy(false);
    })();
    return () => {
      cancelled = true;
    };
    // Runs once when the step opens; `pages` cannot change while OCR is running because editing is disabled.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const page = pages[Math.min(index, pages.length - 1)];
  const setBoxes = (boxes: Rect[]) => {
    setConfirmed(false); // any change to the boxes needs a fresh look
    onChange(pages.map((p) => (p.id === page.id ? { ...p, boxes } : p)));
  };

  function addBox() {
    setBoxes([...page.boxes, { x: page.width * 0.1, y: page.height * 0.1, w: page.width * 0.4, h: page.height * 0.06 }]);
    setSelected(page.boxes.length);
  }

  function deleteBox() {
    if (selected === null) return;
    setBoxes(page.boxes.filter((_, i) => i !== selected));
    setSelected(null);
  }

  async function upload() {
    setUploading(true);
    setError(null);
    try {
      const redacted = await Promise.all(pages.map((p) => burnRedactions(p.blob, p.boxes)));
      const item = await enqueue(meta, redacted, me.id);
      let result: SendResult | undefined = (await flushOutbox(me.id)).get(item.id);
      if (!result) result = (await flushOutbox(me.id)).get(item.id); // a flush that started earlier did not include it
      await outbox.refresh();
      if (result?.outcome === "done" && result.recordId) {
        navigate(`/records/${result.recordId}`);
      } else if (result?.outcome === "fail") {
        setError(`Upload refused: ${result.error}. The redacted copy is listed on the home screen.`);
      } else {
        navigate("/", { state: { notice: "Saved on this device — it will upload when the connection is back." } });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  const count = page.boxes.length;
  const locked = ocrBusy || uploading;
  const allSeen = pages.every((p) => seen.has(p.id));
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Hide names and numbers</h2>
      <p className="text-sm text-slate-600">
        Black boxes are burned into the photo before it leaves this device. Cover every patient name, phone number, address and ID.
      </p>
      {ocrBusy && <p className="rounded-md bg-slate-100 p-3">Finding names…</p>}
      {ocrWarning && <p className="rounded-md bg-amber-50 p-3 text-amber-900">{ocrWarning}</p>}
      {pages.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {pages.map((p, i) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setIndex(i);
                setSelected(null);
              }}
              className={i === index ? primaryButton : secondaryButton}
            >
              Page {i + 1} · {p.boxes.length} {p.boxes.length === 1 ? "box" : "boxes"}
              {seen.has(p.id) ? "" : " · not checked"}
            </button>
          ))}
        </div>
      )}
      <RedactionCanvas key={page.id} url={page.url} width={page.width} height={page.height} boxes={page.boxes} disabled={locked} selected={selected} onSelect={setSelected} onChange={setBoxes} onShown={() => setSeen((s) => (s.has(page.id) ? s : new Set(s).add(page.id)))} />
      <p data-testid="box-count" className="text-sm">
        {count} {count === 1 ? "box" : "boxes"}
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={locked} onClick={addBox} className={secondaryButton}>Add box</button>
        <button type="button" disabled={selected === null || locked} onClick={deleteBox} className={secondaryButton}>Delete box</button>
      </div>
      {!allSeen && pages.length > 1 && <p className="text-sm text-amber-800">Open every page and check it before uploading.</p>}
      <label className="flex items-start gap-2">
        <input type="checkbox" checked={confirmed} disabled={ocrBusy || !allSeen} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1" />
        <span>All names and numbers are covered.</span>
      </label>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={uploading} onClick={onBack} className={secondaryButton}>Back</button>
        <button type="button" disabled={!confirmed || !allSeen || locked} onClick={upload} className={primaryButton}>
          {uploading ? "Uploading…" : "Upload"}
        </button>
      </div>
    </div>
  );
}
