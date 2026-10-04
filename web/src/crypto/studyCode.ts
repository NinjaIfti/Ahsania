import { encodeCrockford } from "./base32";

export const STUDY_CODE_RE = /^AMH-[0-9A-HJKMNP-TV-Z]{10}$/;

export function normalizeRegNo(regNo: string): string {
  return regNo.toUpperCase().replace(/[\s\-/.]/g, "");
}

export async function studyCodeFor(key: CryptoKey, regNo: string): Promise<string> {
  const normalized = normalizeRegNo(regNo);
  if (!normalized) throw new Error("Enter the registration number");
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(normalized)));
  return `AMH-${encodeCrockford(signature).slice(0, 10)}`;
}
