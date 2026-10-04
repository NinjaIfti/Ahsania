import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useCurrentUser } from "../auth/RequireAuth";
import type { OutboxItem } from "../storage/idb";
import { discard as discardItem, flushOutbox, listOutbox } from "./outbox";

export interface OutboxState {
  /** This user's items only. */
  items: OutboxItem[];
  /** Waiting items captured by other users of this device; they upload when those users sign in. */
  othersWaiting: number;
  refresh: () => Promise<void>;
  flush: () => Promise<void>;
  discard: (id: string) => Promise<void>;
}

const OutboxContext = createContext<OutboxState | null>(null);

export function OutboxProvider({ children }: { children: ReactNode }) {
  const me = useCurrentUser();
  const userId = me.id;
  const queryClient = useQueryClient();
  const [all, setAll] = useState<OutboxItem[]>([]);
  const refresh = useCallback(async () => setAll(await listOutbox()), []);
  const flush = useCallback(async () => {
    const results = await flushOutbox(userId);
    // A record that just went up must show in the lists without a reload.
    if ([...results.values()].some((r) => r.outcome === "done")) await queryClient.invalidateQueries({ queryKey: ["records"] });
    await refresh();
  }, [refresh, userId, queryClient]);
  const items = all.filter((item) => item.userId === userId);
  const othersWaiting = all.filter((item) => item.userId !== userId && !item.failed).length;
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

  return <OutboxContext.Provider value={{ items, othersWaiting, refresh, flush, discard }}>{children}</OutboxContext.Provider>;
}

export function useOutbox(): OutboxState {
  const value = useContext(OutboxContext);
  if (!value) throw new Error("useOutbox must be used inside OutboxProvider");
  return value;
}
