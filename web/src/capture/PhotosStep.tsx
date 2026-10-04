import { useRef, useState, type ChangeEvent } from "react";
import { isBlurry } from "../imaging/blur";
import type { PreparedPage } from "../imaging/render";
import { card, primaryButton, secondaryButton } from "../ui/styles";
import { CropEditor } from "./CropEditor";
import type { PageDraft } from "./types";

interface Props {
  pages: PageDraft[];
  onChange: (pages: PageDraft[]) => void;
  onBack: () => void;
  onNext: () => void;
}

export function PhotosStep({ pages, onChange, onBack, onNext }: Props) {
  const [editing, setEditing] = useState<ImageBitmap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError(null);
    try {
      setEditing(await createImageBitmap(file, { imageOrientation: "from-image" }));
    } catch {
      setError("This file could not be opened as an image. Try taking the photo again.");
    }
  }

  function addPage(page: PreparedPage) {
    editing?.close();
    setEditing(null);
    onChange([
      ...pages,
      { id: crypto.randomUUID(), blob: page.blob, url: URL.createObjectURL(page.blob), width: page.width, height: page.height, blur: page.blur, boxes: [], ocrDone: false },
    ]);
  }

  function remove(id: string) {
    const page = pages.find((p) => p.id === id);
    if (page) URL.revokeObjectURL(page.url);
    onChange(pages.filter((p) => p.id !== id));
  }

  if (editing) {
    return (
      <CropEditor
        bitmap={editing}
        onCancel={() => {
          editing.close();
          setEditing(null);
        }}
        onDone={addPage}
      />
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Photos</h2>
      {pages.length === 0 && <p className="text-slate-600">Take a photo of each page. Fill the frame and avoid glare.</p>}
      <ol className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {pages.map((p, i) => (
          <li key={p.id} className={card}>
            <img src={p.url} alt={`Page ${i + 1}`} className="h-40 w-full object-contain" />
            {isBlurry(p.blur) && <p className="mt-1 text-sm text-amber-700">Photo looks blurry — retake?</p>}
            <button type="button" onClick={() => remove(p.id)} className={`${secondaryButton} mt-2 w-full`}>
              Remove page {i + 1}
            </button>
          </li>
        ))}
      </ol>
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" onChange={onFile} className="hidden" data-testid="camera-input" />
      <input ref={galleryRef} type="file" accept="image/*" onChange={onFile} className="hidden" data-testid="gallery-input" />
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => cameraRef.current?.click()} className={primaryButton}>
          {pages.length ? "Take another photo" : "Take photo"}
        </button>
        <button type="button" onClick={() => galleryRef.current?.click()} className={secondaryButton}>
          Choose from gallery
        </button>
      </div>
      <div className="flex gap-2">
        <button type="button" onClick={onBack} className={secondaryButton}>Back</button>
        <button type="button" disabled={pages.length === 0} onClick={onNext} className={primaryButton}>Next: hide names</button>
      </div>
    </div>
  );
}
