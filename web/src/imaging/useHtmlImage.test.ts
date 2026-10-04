// @vitest-environment jsdom
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useHtmlImage } from "./useHtmlImage";

class FakeImage {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private _src = "";
  get src() {
    return this._src;
  }
  set src(value: string) {
    this._src = value;
    setTimeout(() => (value.includes("bad") ? this.onerror?.() : this.onload?.()), 0);
  }
}

beforeEach(() => {
  vi.stubGlobal("Image", FakeImage);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useHtmlImage", () => {
  it("resolves the image, clears it when the url changes, and reports a failed load", async () => {
    const { result, rerender } = renderHook(({ url }) => useHtmlImage(url), { initialProps: { url: "a.png" } });
    expect(result.current).toEqual({ image: null, failed: false });
    await waitFor(() => expect(result.current.image).not.toBeNull());
    expect((result.current.image as unknown as FakeImage).src).toBe("a.png");

    rerender({ url: "b.png" });
    expect(result.current.image).toBeNull();
    await waitFor(() => expect((result.current.image as unknown as FakeImage | null)?.src).toBe("b.png"));

    rerender({ url: "bad.png" });
    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.image).toBeNull();
  });
});
