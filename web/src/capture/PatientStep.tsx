import { useEffect, useState } from "react";
import { api } from "../api/client";
import { inputClass, primaryButton, secondaryButton } from "../ui/styles";
import type { PageDraft } from "./types";

/** Mirrors capture.api.schemas.normalize_reg_no on the server. */
export function normalizeRegNo(raw: string): string | null {
  const value = raw.replace(/\s+/g, "").toUpperCase();
  return /^RC[0-9]{1,30}$/.test(value) ? value : null;
}

/** The first patient ID the server finds on the pages, or null (none found, offline, or no OCR on the server). */
export async function readRegNo(pages: PageDraft[]): Promise<string | null> {
  for (const page of pages) {
    const form = new FormData();
    form.append("page", page.blob, "page.jpg");
    try {
      const { reg_no } = await api<{ reg_no: string | null }>("/read-id", { method: "POST", body: form });
      if (reg_no) return reg_no;
    } catch {
      return null;
    }
  }
  return null;
}

interface Props {
  pages: PageDraft[];
  onBack: () => void;
  /** Throw an Error to show its message here. */
  onUpload: (regNo: string, fillByHand: boolean) => Promise<void>;
}

export function PatientStep({ pages, onBack, onUpload }: Props) {
  const [regNo, setRegNo] = useState("");
  const [reading, setReading] = useState(true);
  const [found, setFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    readRegNo(pages).then((value) => {
      if (cancelled) return;
      setReading(false);
      if (value) {
        setRegNo((typed) => typed || value);
        setFound(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [pages]);

  async function upload(fillByHand: boolean) {
    const value = normalizeRegNo(regNo);
    if (!value) {
      setError("Patient ID must be RC followed by numbers");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await onUpload(value, fillByHand);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Patient ID</h2>
      <label className="block">
        <span className="text-sm font-medium">Patient ID (RC…)</span>
        <input
          value={regNo}
          onChange={(e) => setRegNo(e.target.value)}
          placeholder={reading ? "Reading from the photos…" : "RC12345"}
          autoComplete="off"
          autoCapitalize="characters"
          className={`${inputClass} font-mono`}
        />
      </label>
      {reading && <p role="status" className="text-sm text-slate-600">Reading the patient ID from the photos…</p>}
      {!reading && found && <p className="text-sm text-slate-600">Read from the photo — check it is right.</p>}
      {!reading && !found && <p className="text-sm text-amber-700">No patient ID found on the photos — type it.</p>}
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={uploading} onClick={onBack} className={secondaryButton}>Back</button>
        <button type="button" disabled={uploading || !regNo.trim()} onClick={() => upload(false)} className={primaryButton}>
          Let the AI fill it
        </button>
        <button type="button" disabled={uploading || !regNo.trim()} onClick={() => upload(true)} className={secondaryButton}>
          I'll fill it myself
        </button>
      </div>
      {uploading && <p role="status">Uploading…</p>}
    </div>
  );
}
