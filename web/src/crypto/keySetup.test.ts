import { describe, expect, it } from "vitest";
import { checkEnteredKey } from "./keySetup";

const KEY = "000G40R40M30E209185GR38E1W8124GK2GAHC5RR34D1P70X3RFG";

describe("checkEnteredKey", () => {
  it("accepts the printed format when it matches the hospital key", async () => {
    const typed = "000g-40r4-0m30-e209-185g-r38e-1w81-24gk-2gah-c5rr-34d1-p70x-3rfg";
    expect(await checkEnteredKey(typed, "K-B9FF")).toEqual({ ok: true, canonical: KEY, fingerprint: "K-B9FF" });
  });
  it("explains a mismatch and shows the expected fingerprint", async () => {
    expect(await checkEnteredKey(KEY, "K-0000")).toEqual({
      ok: false,
      message: "This key doesn't match the hospital key (K-0000). Check for typos.",
    });
  });
  it("explains a malformed key", async () => {
    expect(await checkEnteredKey("1234", null)).toEqual({ ok: false, message: "The key must be 52 characters (ignoring dashes)" });
  });
  it("accepts any well-formed key before a hospital key exists", async () => {
    expect((await checkEnteredKey(KEY, null)).ok).toBe(true);
  });
});
