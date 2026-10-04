import { openDB, type DBSchema, type IDBPDatabase } from "idb";

export interface StoredDeviceKey {
  cryptoKey: CryptoKey;
  fingerprint: string;
}

export interface OutboxMeta {
  study_code: string;
  template_key: string;
  key_fingerprint: string;
}

/** A redacted upload waiting to be sent. Never holds unredacted images. */
export interface OutboxItem {
  id: string;
  createdAt: number;
  meta: OutboxMeta;
  pages: ArrayBuffer[];
  attempts: number;
  error: string | null;
  failed: boolean;
}

interface CaptureDb extends DBSchema {
  device: { key: string; value: StoredDeviceKey };
  outbox: { key: string; value: OutboxItem };
}

let dbPromise: Promise<IDBPDatabase<CaptureDb>> | null = null;

export function getDb(): Promise<IDBPDatabase<CaptureDb>> {
  dbPromise ??= openDB<CaptureDb>("amcgh-capture", 1, {
    upgrade(db) {
      db.createObjectStore("device");
      db.createObjectStore("outbox", { keyPath: "id" });
    },
  });
  return dbPromise;
}

export function resetDbForTests(): void {
  dbPromise = null;
}
