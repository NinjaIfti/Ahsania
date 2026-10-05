import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, json } from "../api/client";
import { useAccounts } from "../api/hooks";
import type { Account, Role } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { ROLE_LABEL } from "../auth/roles";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";

export default function AccountsPage() {
  const me = useCurrentUser();
  const accounts = useAccounts(me.role === "admin");
  if (me.role !== "admin") return <p>Only an admin can manage accounts.</p>;
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Accounts</h1>
      {accounts.isPending ? (
        <p>Loading…</p>
      ) : accounts.isError ? (
        <p role="alert" className="text-red-700">{accounts.error.message}</p>
      ) : (
        <AccountTable accounts={accounts.data} myId={me.id} />
      )}
      <CreateAccount />
    </div>
  );
}

function AccountTable({ accounts, myId }: { accounts: Account[]; myId: number }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="p-3">Name</th>
            <th className="p-3">ID</th>
            <th className="p-3">Role</th>
            <th className="p-3">Status</th>
            <th className="p-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200">
          {accounts.map((a) => (
            <AccountRow key={a.id} account={a} isMe={a.id === myId} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AccountRow({ account: a, isMe }: { account: Account; isMe: boolean }) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function update(change: { active?: boolean; password?: string }, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      await api<Account>(`/admin/users/${a.id}`, { method: "PATCH", body: json(change) });
      await queryClient.invalidateQueries({ queryKey: ["accounts"] });
      setPassword(null);
      setMessage(done);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Change failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr>
      <td className="p-3">{a.name}</td>
      <td className="p-3 font-mono">{a.username}</td>
      <td className="p-3">{ROLE_LABEL[a.role]}</td>
      <td className="p-3">{a.active ? "Active" : "Deactivated"}</td>
      <td className="space-y-2 p-3">
        <div className="flex flex-wrap gap-2">
          {!isMe && (
            <button type="button" disabled={busy} onClick={() => update({ active: !a.active }, a.active ? "Deactivated" : "Reactivated")} className={secondaryButton}>
              {a.active ? "Deactivate" : "Reactivate"}
            </button>
          )}
          {password === null && (
            <button type="button" disabled={busy} onClick={() => setPassword("")} className={secondaryButton}>
              Set password…
            </button>
          )}
        </div>
        {password !== null && (
          <div className="flex flex-wrap items-end gap-2">
            <label className="block">
              <span className="text-xs font-medium">New password for {a.username}</span>
              <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
            </label>
            <button type="button" disabled={busy || password.length < 10} onClick={() => update({ password }, "Password changed")} className={primaryButton}>
              Save
            </button>
            <button type="button" onClick={() => setPassword(null)} className={secondaryButton}>
              Cancel
            </button>
          </div>
        )}
        {message && <p role="status" className="text-xs text-slate-700">{message}</p>}
      </td>
    </tr>
  );
}

function CreateAccount() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("doctor");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api<Account>("/admin/users", { method: "POST", body: json({ name, username, password, role }) });
      await queryClient.invalidateQueries({ queryKey: ["accounts"] });
      setName("");
      setUsername("");
      setPassword("");
      setRole("doctor");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className={`${card} max-w-md space-y-3`}>
      <h2 className="text-lg font-semibold">New account</h2>
      <label className="block">
        <span className="text-sm font-medium">Name</span>
        <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Dr. Rahman" className={inputClass} />
      </label>
      <label className="block">
        <span className="text-sm font-medium">ID</span>
        <input required value={username} onChange={(e) => setUsername(e.target.value)} placeholder="dr.rahman" autoComplete="off" autoCapitalize="none" spellCheck={false} className={`${inputClass} font-mono`} />
      </label>
      <label className="block">
        <span className="text-sm font-medium">Password</span>
        <input type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" className={inputClass} />
      </label>
      <p className="-mt-2 text-xs text-slate-600">At least 10 characters.</p>
      <label className="block">
        <span className="text-sm font-medium">Role</span>
        <select value={role} onChange={(e) => setRole(e.target.value as Role)} className={inputClass}>
          <option value="doctor">Doctor</option>
          <option value="admin">Admin</option>
        </select>
      </label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button type="submit" disabled={busy} className={primaryButton}>
        Create account
      </button>
    </form>
  );
}
