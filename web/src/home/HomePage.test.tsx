// @vitest-environment jsdom
import "fake-indexeddb/auto";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IDBFactory } from "fake-indexeddb";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { enqueue, listOutbox } from "../outbox/outbox";
import { OutboxProvider } from "../outbox/OutboxContext";
import { getDb, resetDbForTests } from "../storage/idb";
import HomePage from "./HomePage";

vi.mock("../auth/RequireAuth", () => ({
  useCurrentUser: () => ({ id: 1, name: "Demo Uploader", email: "uploader@amcgh.test", role: "uploader", institution: "AMCGH" }),
}));
vi.mock("../api/hooks", () => ({ useRecords: () => ({ isPending: false, data: [] }) }));
vi.mock("../crypto/keyStore", () => ({ useDeviceKey: () => ({ data: null }) }));

const REASON = "This device's key doesn't match — ask your hospital admin.";
const REFUSED = `Upload refused for AMH-N0ZDG4KM8V: ${REASON}`;

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetDbForTests();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("HomePage outbox", () => {
  it("keeps a refused upload visible with the server's reason until it is discarded", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const item = await enqueue({ study_code: "AMH-N0ZDG4KM8V", template_key: "radiology_report", key_fingerprint: "K-B9FF" }, [
      new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], { type: "image/jpeg" }),
    ], 1);
    await (await getDb()).put("outbox", { ...item, failed: true, attempts: 1, error: REASON });

    render(
      <MemoryRouter>
        <OutboxProvider>
          <HomePage />
        </OutboxProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText(REFUSED)).toBeTruthy();
    expect(screen.queryByText(/waiting to upload/)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Discard" }));

    await waitFor(() => expect(screen.queryByText(REFUSED)).toBeNull());
    expect(await listOutbox()).toEqual([]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("shows another user's waiting upload without sending or discarding it", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    await enqueue({ study_code: "AMH-N0ZDG4KM8V", template_key: "radiology_report", key_fingerprint: "K-B9FF" }, [
      new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], { type: "image/jpeg" }),
    ], 2);

    render(
      <MemoryRouter>
        <OutboxProvider>
          <HomePage />
        </OutboxProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("1 waiting for another user to sign in on this device")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull();
    expect(screen.queryByText(/waiting to upload/)).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(await listOutbox()).toHaveLength(1);
  });
});
