import { decodeCrockford, encodeCrockford } from "./base32";

export const KEY_BYTES = 32;

export function generateKeyString(): string {
  return encodeCrockford(crypto.getRandomValues(new Uint8Array(KEY_BYTES)));
}

/** Normalizes a typed key (case, dashes, O/0, I/L/1) to its 52-character form. */
export function canonicalKeyString(input: string): string {
  return encodeCrockford(decodeCrockford(input, KEY_BYTES));
}

export function formatKeyForPrint(key: string): string {
  return (key.match(/.{1,4}/g) ?? []).join("-");
}

export async function fingerprintOf(keyString: string): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`amcgh-fingerprint:${keyString}`)));
  const hex = Array.from(digest.slice(0, 2), (b) => b.toString(16).padStart(2, "0")).join("");
  return `K-${hex.toUpperCase()}`;
}

export function importHmacKey(keyString: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", decodeCrockford(keyString, KEY_BYTES), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
}
