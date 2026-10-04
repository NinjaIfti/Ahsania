import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api, json } from "../api/client";
import type { Me } from "../api/types";
import { card, inputClass, primaryButton } from "../ui/styles";

export default function LoginPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/login", { method: "POST", body: json({ email, password }) });
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
    <main className="mx-auto mt-16 max-w-sm px-4">
      <h1 className="mb-6 text-center text-2xl font-semibold">AMCGH Data Capture</h1>
      <form onSubmit={submit} className={`${card} space-y-4`}>
        <label className="block">
          <span className="text-sm font-medium">Email</span>
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
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
    </main>
  );
}
