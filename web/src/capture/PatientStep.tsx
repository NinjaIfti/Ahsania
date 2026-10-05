import { useState, type FormEvent } from "react";
import { card, inputClass, primaryButton } from "../ui/styles";

/** Mirrors capture.api.schemas.normalize_reg_no on the server. */
export function normalizeRegNo(raw: string): string | null {
  const value = raw.replace(/\s+/g, "").toUpperCase();
  return /^RC[0-9]{1,30}$/.test(value) ? value : null;
}

export function PatientStep({ initial, onDone }: { initial: string; onDone: (regNo: string) => void }) {
  const [regNo, setRegNo] = useState(initial);
  const [error, setError] = useState<string | null>(null);

  function next(event: FormEvent) {
    event.preventDefault();
    const value = normalizeRegNo(regNo);
    if (!value) {
      setError("Patient ID must be RC followed by numbers");
      return;
    }
    onDone(value);
  }

  return (
    <form onSubmit={next} className={`${card} space-y-3`}>
      <label className="block">
        <span className="text-sm font-medium">Patient ID (RC…)</span>
        <input
          value={regNo}
          onChange={(e) => setRegNo(e.target.value)}
          placeholder="RC12345"
          autoComplete="off"
          autoCapitalize="characters"
          required
          className={`${inputClass} font-mono`}
        />
      </label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button type="submit" className={primaryButton}>Continue</button>
    </form>
  );
}
