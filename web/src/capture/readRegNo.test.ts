import { afterEach, describe, expect, it, vi } from "vitest";
import { readRegNo } from "./PatientStep";
import type { PageDraft } from "./types";

const page = (id: string): PageDraft => ({ id, blob: new Blob(["x"]), url: "", width: 1, height: 1, blur: 100 });
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => vi.unstubAllGlobals());

describe("readRegNo", () => {
  it("returns the first ID found, trying the pages in order", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(reply({ reg_no: null })).mockResolvedValueOnce(reply({ reg_no: "RC42" }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await readRegNo([page("a"), page("b"), page("c")])).toBe("RC42");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/read-id");
  });

  it("gives up quietly when the server cannot read photos or is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply({ detail: "no OCR" }, 503)));
    expect(await readRegNo([page("a")])).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect(await readRegNo([page("a")])).toBeNull();
  });
});
