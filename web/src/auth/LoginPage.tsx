import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api, json } from "../api/client";
import type { Me } from "../api/types";
import { brandBand, card, inputClass, primaryButton } from "../ui/styles";

export default function LoginPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/login", { method: "POST", body: json({ username, password }) });
      queryClient.clear(); // a new user must never see the previous user's cached records
      queryClient.setQueryData(["me"], me);
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen">
      <div className={`${brandBand} px-4 pb-24 pt-14 text-center`}>
        <span aria-hidden="true" className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-white/15 text-2xl font-bold">
          A
        </span>
        <h1 className="text-2xl font-bold">AMCGH Data Capture</h1>
        <p className="mt-1 text-sm text-white/80">Ahsania Mission Cancer &amp; General Hospital × NSU</p>
      </div>
      <div className="relative -mt-16 px-4">
        <form onSubmit={submit} className={`${card} mx-auto max-w-sm space-y-4 p-6 shadow-lg`}>
          <label className="block">
            <span className="text-sm font-medium">ID</span>
            <input type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} required value={username} onChange={(e) => setUsername(e.target.value)} className={inputClass} />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Password</span>
            <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
          </label>
          {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
          <button type="submit" disabled={busy} className={`${primaryButton} w-full`}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}
