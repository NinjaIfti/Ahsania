import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { dangerButton, secondaryButton } from "../ui/styles";

/** Delete a capture after an on-screen "are you sure" (no browser dialog: the Android app may not show one). */
export function DeleteButton({ recordId, onDeleted }: { recordId: string; onDeleted?: () => void }) {
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api<void>(`/records/${recordId}`, { method: "DELETE" });
      queryClient.removeQueries({ queryKey: ["record", recordId] });
      void queryClient.invalidateQueries({ queryKey: ["records"] });
      onDeleted?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
      setBusy(false);
    }
  }

  if (!asking) {
    return (
      <button type="button" onClick={() => setAsking(true)} className="rounded-lg px-3 py-1.5 text-sm font-semibold text-red-700 hover:bg-red-50">
        Delete
      </button>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-2 text-sm">
      <span className="font-medium text-red-800">Delete this capture?</span>
      <button type="button" disabled={busy} onClick={() => void remove()} className={dangerButton}>
        Yes, delete
      </button>
      <button type="button" disabled={busy} onClick={() => setAsking(false)} className={secondaryButton}>
        Cancel
      </button>
      {error && (
        <span role="alert" className="w-full text-red-700">
          {error}
        </span>
      )}
    </span>
  );
}
