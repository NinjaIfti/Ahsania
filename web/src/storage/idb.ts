import { openDB, type DBSchema, type IDBPDatabase } from "idb";

export interface OutboxMeta {
  reg_no: string;
  template_key: string;
  fill_by_hand: boolean;
}

/** An upload waiting to be sent. */
export interface OutboxItem {
  id: string;
  /** The user who captured it. Only that user's session may send it. */
  userId: number;
  createdAt: number;
  meta: OutboxMeta;
  pages: ArrayBuffer[];
  attempts: number;
  error: string | null;
  failed: boolean;
}

interface CaptureDb extends DBSchema {
  outbox: { key: string; value: OutboxItem };
}

let dbPromise: Promise<IDBPDatabase<CaptureDb>> | null = null;

export function getDb(): Promise<IDBPDatabase<CaptureDb>> {
  dbPromise ??= openDB<CaptureDb>("amcgh-capture", 2, {
    upgrade(db, oldVersion) {
      if (oldVersion < 1) db.createObjectStore("outbox", { keyPath: "id" });
      // Version 1 also kept the device key, which is no longer used.
      if ((db.objectStoreNames as DOMStringList).contains("device")) db.deleteObjectStore("device" as never);
    },
  });
  return dbPromise;
}

export function resetDbForTests(): void {
  dbPromise = null;
}
