// @vitest-environment jsdom
import "fake-indexeddb/auto";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IDBFactory } from "fake-indexeddb";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Me, RecordSummary } from "../api/types";
import { enqueue, listOutbox } from "../outbox/outbox";
import { OutboxProvider } from "../outbox/OutboxContext";
import { getDb, resetDbForTests } from "../storage/idb";
import HomePage from "./HomePage";

const DOCTOR: Me = { id: 1, name: "Demo Doctor", username: "doctor", role: "doctor" };
const ADMIN: Me = { id: 9, name: "Demo Admin", username: "admin", role: "admin" };
const state: { me: Me; records: RecordSummary[] } = { me: DOCTOR, records: [] };

vi.mock("../auth/RequireAuth", () => ({ useCurrentUser: () => state.me }));
vi.mock("../api/hooks", () => ({
  useRecords: (filter: { status?: string }) => ({ isPending: false, data: state.records.filter((r) => r.status === filter.status) }),
}));

function record(id: string, status: RecordSummary["status"], lastAction = "upload"): RecordSummary {
  return {
    id,
    reg_no: `RC${id}`,
    template_key: "radiology_report",
    template_title: `Report ${id}`,
    template_version: 1,
    status,
    extraction_status: "done",
    document_date: null,
    created_by_id: 1,
    created_by_name: "Demo Doctor",
    created_at: "2026-10-05T10:00:00Z",
    updated_at: `2026-10-05T10:0${id}:00Z`,
    last_event: { action: lastAction, comment: null, actor_name: "Demo Admin", created_at: "2026-10-05T10:00:00Z" },
    ai_amber: 0,
    ai_red: 0,
  };
}

const PAGE = new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], { type: "image/jpeg" });
const META = { reg_no: "RC00123", template_key: "radiology_report", fill_by_hand: false };
const REASON = "This upload ID is already in use";
const REFUSED = `Upload refused for RC00123: ${REASON}`;

function renderHome() {
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <OutboxProvider>
          <HomePage />
        </OutboxProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetDbForTests();
  state.me = DOCTOR;
  state.records = [];
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("HomePage outbox", () => {
  it("keeps a refused upload visible with the server's reason until it is discarded", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const item = await enqueue(META, [PAGE], 1);
    await (await getDb()).put("outbox", { ...item, failed: true, attempts: 1, error: REASON });

    renderHome();

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
    await enqueue(META, [PAGE], 2);

    renderHome();

    expect(await screen.findByText("1 waiting for another user to sign in on this device")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull();
    expect(screen.queryByText(/waiting to upload/)).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(await listOutbox()).toHaveLength(1);
  });
});

describe("HomePage panels", () => {
  it("puts a doctor's sent-back draft apart from the other drafts", async () => {
    vi.stubGlobal("fetch", vi.fn());
    state.records = [record("1", "draft", "return"), record("2", "draft", "edit")];

    renderHome();

    const sentBack = (await screen.findByRole("heading", { name: "Sent back to me" })).closest("section")!;
    expect(within(sentBack).getByText("Report 1")).toBeTruthy();
    expect(within(sentBack).queryByText("Report 2")).toBeNull();
    const drafts = screen.getByRole("heading", { name: "My drafts" }).closest("section")!;
    expect(within(drafts).getByText("Report 2")).toBeTruthy();
    expect(screen.getByRole("link", { name: "New capture" })).toBeTruthy();
  });

  it("shows the admin the records waiting for approval, oldest first", async () => {
    vi.stubGlobal("fetch", vi.fn());
    state.me = ADMIN;
    state.records = [record("3", "pending_admin"), record("1", "pending_admin"), record("2", "draft")];

    renderHome();

    expect(await screen.findByRole("heading", { name: "Waiting for admin" })).toBeTruthy();
    const titles = screen.getAllByText(/^Report /).map((el) => el.textContent);
    expect(titles).toEqual(["Report 1", "Report 3"]);
    expect(screen.queryByRole("link", { name: "New capture" })).toBeNull();
  });
});
