import { errorMessage } from "../api/client";
import { getDb, type OutboxItem, type OutboxMeta } from "../storage/idb";

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

export async function enqueue(meta: OutboxMeta, pages: Blob[]): Promise<OutboxItem> {
  const item: OutboxItem = {
    id: crypto.randomUUID(),
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
    const record = body as { id: string };
    return { outcome, recordId: record.id };
  }
  return { outcome, error: errorMessage(res.status, body) };
}

async function runFlush(fetchImpl: typeof fetch): Promise<Map<string, SendResult>> {
  const results = new Map<string, SendResult>();
  const db = await getDb();
  for (const item of await listOutbox()) {
    if (item.failed) continue;
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

let inFlight: Promise<Map<string, SendResult>> | null = null;

/** Send every waiting item once. Overlapping calls share the same run so nothing is sent twice. */
export function flushOutbox(fetchImpl: typeof fetch = fetch): Promise<Map<string, SendResult>> {
  inFlight ??= runFlush(fetchImpl).finally(() => {
    inFlight = null;
  });
  return inFlight;
}
