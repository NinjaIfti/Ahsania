import { describe, expect, it } from "vitest";
import { decodeCrockford, encodeCrockford } from "./base32";
import { canonicalKeyString, fingerprintOf, formatKeyForPrint, importHmacKey } from "./deviceKey";
import { STUDY_CODE_RE, normalizeRegNo, studyCodeFor } from "./studyCode";

// Reference values computed independently with Python's hmac/hashlib.
const BYTES_0_31 = Uint8Array.from({ length: 32 }, (_, i) => i);
const KEY = "000G40R40M30E209185GR38E1W8124GK2GAHC5RR34D1P70X3RFG";
const KEY_FF = "Z".repeat(51) + "G";

describe("Crockford base32", () => {
  it("encodes 32 bytes as 52 characters", () => {
    expect(encodeCrockford(BYTES_0_31)).toBe(KEY);
    expect(encodeCrockford(new Uint8Array(32).fill(255))).toBe(KEY_FF);
  });
  it("round-trips", () => {
    expect(Array.from(decodeCrockford(KEY, 32))).toEqual(Array.from(BYTES_0_31));
  });
  it("accepts lowercase, dashes and look-alike letters when a key is typed", () => {
    const typed = formatKeyForPrint(KEY).toLowerCase().replace(/1/g, "l").replace(/0/g, "o");
    expect(canonicalKeyString(typed)).toBe(KEY);
  });
  it("rejects a key of the wrong length", () => {
    expect(() => canonicalKeyString(KEY.slice(0, 51))).toThrow("The key must be 52 characters (ignoring dashes)");
  });
  it("rejects characters outside the alphabet", () => {
    expect(() => canonicalKeyString(KEY.slice(0, 51) + "U")).toThrow('Invalid character "U" in key');
  });
});

describe("fingerprint", () => {
  it("matches the reference values", async () => {
    expect(await fingerprintOf(KEY)).toBe("K-B9FF");
    expect(await fingerprintOf(KEY_FF)).toBe("K-786D");
  });
});

describe("study code", () => {
  it("normalizes registration numbers", () => {
    expect(normalizeRegNo(" amh-001/23. ")).toBe("AMH00123");
  });
  it.each([
    ["AMH-00123", "AMH-N0ZDG4KM8V"],
    ["amh 00123", "AMH-N0ZDG4KM8V"],
    ["AMH/00123.", "AMH-N0ZDG4KM8V"],
    ["12345/2026", "AMH-MHNZ0NHAA4"],
    ["A.B-C d", "AMH-0KWJ57170Y"],
  ])("%s -> %s", async (regNo, expected) => {
    const code = await studyCodeFor(await importHmacKey(KEY), regNo);
    expect(code).toBe(expected);
    expect(code).toMatch(STUDY_CODE_RE);
  });
  it("depends on the hospital key", async () => {
    expect(await studyCodeFor(await importHmacKey(KEY_FF), "AMH00123")).toBe("AMH-E6RRNCP0BD");
  });
  it("refuses an empty registration number", async () => {
    await expect(studyCodeFor(await importHmacKey(KEY), " - ")).rejects.toThrow("Enter the registration number");
  });
  it("keeps the imported key non-extractable", async () => {
    expect((await importHmacKey(KEY)).extractable).toBe(false);
  });
});
