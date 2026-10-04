import { useState, type FormEvent } from "react";
import { studyCodeFor } from "../crypto/studyCode";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";

interface Props {
  cryptoKey: CryptoKey;
  onDone: (studyCode: string) => void;
}

export function PatientStep({ cryptoKey, onDone }: Props) {
  const [regNo, setRegNo] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function compute(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      setCode(await studyCodeFor(cryptoKey, regNo));
      setRegNo(""); // the registration number never leaves this screen
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (code) {
    return (
      <div className={`${card} space-y-3`}>
        <p className="text-sm text-slate-600">Study code</p>
        <p data-testid="study-code" className="font-mono text-2xl">{code}</p>
        <p className="text-sm text-slate-600">The registration number has been cleared from this screen.</p>
        <div className="flex gap-2">
          <button type="button" onClick={() => setCode(null)} className={secondaryButton}>Different patient</button>
          <button type="button" onClick={() => onDone(code)} className={primaryButton}>Continue</button>
        </div>
      </div>
    );
  }
  return (
    <form onSubmit={compute} className={`${card} space-y-3`}>
      <label className="block">
        <span className="text-sm font-medium">Hospital registration number</span>
        <input value={regNo} onChange={(e) => setRegNo(e.target.value)} autoComplete="off" required className={inputClass} />
      </label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button type="submit" className={primaryButton}>Get study code</button>
    </form>
  );
}
