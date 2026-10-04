import "fake-indexeddb/auto";
import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetDbForTests } from "../storage/idb";
import { classifyStatus, discard, enqueue, flushOutbox, listOutbox } from "./outbox";

const META = { study_code: "AMH-N0ZDG4KM8V", template_key: "radiology_report", key_fingerprint: "K-B9FF" };
const jpeg = () => new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], { type: "image/jpeg" });
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const asFetch = (f: (...args: never[]) => Promise<Response>) => f as unknown as typeof fetch;

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetDbForTests();
});

describe("classifyStatus", () => {
  it.each([
    [201, "done"],
    [401, "retry"],
    [408, "retry"],
    [429, "retry"],
    [503, "retry"],
    [409, "fail"],
    [413, "fail"],
    [415, "fail"],
    [422, "fail"],
  ] as const)("%i -> %s", (status, outcome) => {
    expect(classifyStatus(status)).toBe(outcome);
  });
});

describe("outbox", () => {
  it("stores redacted pages as bytes", async () => {
    await enqueue(META, [jpeg(), jpeg()], 1);
    const [item] = await listOutbox();
    expect(item.meta).toEqual(META);
    expect(item.pages.map((p) => p.byteLength)).toEqual([4, 4]);
    expect(item).toMatchObject({ attempts: 0, error: null, failed: false });
  });

  it("sends meta and pages, then removes the item", async () => {
    const item = await enqueue(META, [jpeg(), jpeg()], 1);
    const fetchMock = vi.fn(async () => reply(201, { id: "rec-1", duplicate_of: [] }));
    const results = await flushOutbox(1, asFetch(fetchMock));
    expect(results.get(item.id)).toEqual({ outcome: "done", recordId: "rec-1" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/records");
    const form = init.body as FormData;
    expect(JSON.parse(form.get("meta") as string)).toEqual({ ...META, client_upload_id: item.id });
    expect(form.getAll("pages")).toHaveLength(2);
    expect(await listOutbox()).toEqual([]);
  });

  it("keeps the item after a server error and sends it later", async () => {
    const item = await enqueue(META, [jpeg()], 1);
    const sentMeta: { client_upload_id: string }[] = [];
    const record = (status: number, body: unknown) =>
      asFetch(async (_url: never, init: RequestInit) => {
        sentMeta.push(JSON.parse((init.body as FormData).get("meta") as string));
        return reply(status, body);
      });
    await flushOutbox(1, record(503, { detail: "Service unavailable" }));
    expect((await listOutbox())[0]).toMatchObject({ id: item.id, attempts: 1, failed: false, error: "Service unavailable" });
    await flushOutbox(1, record(201, { id: "rec-2", duplicate_of: [] }));
    expect(await listOutbox()).toEqual([]);
    expect(sentMeta).toHaveLength(2);
    expect(sentMeta[1].client_upload_id).toBe(sentMeta[0].client_upload_id);
    expect(sentMeta[0].client_upload_id).toBe(item.id);
  });

  it("keeps the item when a 2xx reply has no record id", async () => {
    await enqueue(META, [jpeg()], 1);
    const results = await flushOutbox(1, asFetch(async () => reply(201, {})));
    expect([...results.values()][0]).toEqual({ outcome: "retry", error: "Unexpected reply from the server — will retry" });
    expect((await listOutbox())[0]).toMatchObject({ attempts: 1, failed: false });

    await flushOutbox(1, asFetch(async () => new Response("<html>proxy</html>", { status: 200, headers: { "Content-Type": "text/html" } })));
    expect((await listOutbox())[0]).toMatchObject({ attempts: 2, failed: false });
  });

  it("keeps the item when the session expired", async () => {
    await enqueue(META, [jpeg()], 1);
    await flushOutbox(1, asFetch(async () => reply(401, { detail: "Not logged in" })));
    expect((await listOutbox())[0]).toMatchObject({ failed: false, attempts: 1 });
  });

  it("keeps the item when offline", async () => {
    await enqueue(META, [jpeg()], 1);
    const results = await flushOutbox(
      1,
      asFetch(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    expect([...results.values()][0]).toEqual({ outcome: "retry", error: "No connection — will retry" });
    expect(await listOutbox()).toHaveLength(1);
  });

  it("sets a refused upload aside with the server's reason and stops retrying it", async () => {
    await enqueue(META, [jpeg()], 1);
    await flushOutbox(1, asFetch(async () => reply(409, { detail: "This device's key doesn't match — ask your hospital admin." })));
    const [item] = await listOutbox();
    expect(item.failed).toBe(true);
    expect(item.error).toBe("This device's key doesn't match — ask your hospital admin.");
    const fetchMock = vi.fn();
    await flushOutbox(1, asFetch(fetchMock));
    expect(fetchMock).not.toHaveBeenCalled();
    await discard(item.id);
    expect(await listOutbox()).toEqual([]);
  });

  it("sends only the signed-in user's items", async () => {
    const mine = await enqueue(META, [jpeg()], 1);
    const theirs = await enqueue(META, [jpeg()], 2);
    const fetchMock = vi.fn(async () => reply(201, { id: "rec-4", duplicate_of: [] }));
    const results = await flushOutbox(2, asFetch(fetchMock));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect([...results.keys()]).toEqual([theirs.id]);
    expect((await listOutbox()).map((i) => i.id)).toEqual([mine.id]);
  });

  it("never sends an item twice when flushes overlap", async () => {
    await enqueue(META, [jpeg()], 1);
    const fetchMock = vi.fn(async () => reply(201, { id: "rec-3", duplicate_of: [] }));
    await Promise.all([flushOutbox(1, asFetch(fetchMock)), flushOutbox(1, asFetch(fetchMock))]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
