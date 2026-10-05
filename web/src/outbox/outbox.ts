import { errorMessage } from "../api/client";
import { getDb, type OutboxItem, type OutboxMeta } from "../storage/idb";
import { newId } from "../storage/id";

export type SendOutcome = "done" | "retry" | "fail";

export interface SendResult {
  outcome: SendOutcome;
  recordId?: string;
  error?: string;
}

export function classifyStatus(status: number): SendOutcome {
  if (status >= 200 && status < 300) return "done";
  if (status === 401 || status === 408 || status === 429 || status >= 500) return "retry";
  return "fail";
}

export async function enqueue(meta: OutboxMeta, pages: Blob[], userId: number): Promise<OutboxItem> {
  const item: OutboxItem = {
    id: newId(),
    userId,
    createdAt: Date.now(),
    meta,
    pages: await Promise.all(pages.map((page) => page.arrayBuffer())),
    attempts: 0,
    error: null,
    failed: false,
  };
  await (await getDb()).put("outbox", item);
  return item;
}

export async function listOutbox(): Promise<OutboxItem[]> {
  return (await (await getDb()).getAll("outbox")).sort((a, b) => a.createdAt - b.createdAt);
}

export async function discard(id: string): Promise<void> {
  await (await getDb()).delete("outbox", id);
}

export async function sendItem(item: OutboxItem, fetchImpl: typeof fetch = fetch): Promise<SendResult> {
  const form = new FormData();
  // The same client_upload_id goes out on every retry, so the server can recognise a replay.
  form.append("meta", JSON.stringify({ ...item.meta, client_upload_id: item.id }));
  item.pages.forEach((bytes, i) => form.append("pages", new Blob([bytes], { type: "image/jpeg" }), `page-${i + 1}.jpg`));
  let res: Response;
  try {
    res = await fetchImpl("/api/records", { method: "POST", body: form, credentials: "same-origin" });
  } catch {
    return { outcome: "retry", error: "No connection — will retry" };
  }
  const body: unknown = await res.json().catch(() => null);
  const outcome = classifyStatus(res.status);
  if (outcome === "done") {
    const id = (body as { id?: unknown } | null)?.id;
    if (typeof id !== "string") return { outcome: "retry", error: "Unexpected reply from the server — will retry" };
    return { outcome, recordId: id };
  }
  return { outcome, error: errorMessage(res.status, body) };
}

async function runFlush(userId: number, fetchImpl: typeof fetch): Promise<Map<string, SendResult>> {
  const results = new Map<string, SendResult>();
  const db = await getDb();
  for (const item of await listOutbox()) {
    if (item.userId !== userId || item.failed) continue;
    const result = await sendItem(item, fetchImpl);
    results.set(item.id, result);
    if (result.outcome === "done") {
      await db.delete("outbox", item.id);
    } else {
      await db.put("outbox", { ...item, attempts: item.attempts + 1, error: result.error ?? null, failed: result.outcome === "fail" });
    }
  }
  return results;
}

const inFlight = new Map<number, Promise<Map<string, SendResult>>>();

/** Send this user's waiting items once. Overlapping calls for the same user share one run so nothing is sent twice. */
export function flushOutbox(userId: number, fetchImpl: typeof fetch = fetch): Promise<Map<string, SendResult>> {
  let run = inFlight.get(userId);
  if (!run) {
    run = runFlush(userId, fetchImpl).finally(() => {
      inFlight.delete(userId);
    });
    inFlight.set(userId, run);
  }
  return run;
}
