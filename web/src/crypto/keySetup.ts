import { canonicalKeyString, fingerprintOf } from "./deviceKey";

export type KeyCheck = { ok: true; canonical: string; fingerprint: string } | { ok: false; message: string };

export async function checkEnteredKey(input: string, expected: string | null): Promise<KeyCheck> {
  let canonical: string;
  try {
    canonical = canonicalKeyString(input);
  } catch (e) {
    return { ok: false, message: (e as Error).message };
  }
  const fingerprint = await fingerprintOf(canonical);
  if (expected !== null && fingerprint !== expected) {
    return { ok: false, message: `This key doesn't match the hospital key (${expected}). Check for typos.` };
  }
  return { ok: true, canonical, fingerprint };
}
