import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { OutboxItem } from "../storage/idb";
import { discard as discardItem, flushOutbox, listOutbox } from "./outbox";

export interface OutboxState {
  items: OutboxItem[];
  refresh: () => Promise<void>;
  flush: () => Promise<void>;
  discard: (id: string) => Promise<void>;
}

const OutboxContext = createContext<OutboxState | null>(null);

export function OutboxProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<OutboxItem[]>([]);
  const refresh = useCallback(async () => setItems(await listOutbox()), []);
  const flush = useCallback(async () => {
    await flushOutbox();
    await refresh();
  }, [refresh]);
  const discard = useCallback(
    async (id: string) => {
      await discardItem(id);
      await refresh();
    },
    [refresh],
  );

  useEffect(() => {
    void flush();
    const timer = window.setInterval(() => void flush(), 30_000);
    const onOnline = () => void flush();
    window.addEventListener("online", onOnline);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", onOnline);
    };
  }, [flush]);

  return <OutboxContext.Provider value={{ items, refresh, flush, discard }}>{children}</OutboxContext.Provider>;
}

export function useOutbox(): OutboxState {
  const value = useContext(OutboxContext);
  if (!value) throw new Error("useOutbox must be used inside OutboxProvider");
  return value;
}
