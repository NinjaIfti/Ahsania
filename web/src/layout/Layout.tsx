import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router";
import { api } from "../api/client";
import { useCurrentUser } from "../auth/RequireAuth";
import { ROLE_LABEL } from "../auth/roles";
import { OutboxProvider, useOutbox } from "../outbox/OutboxContext";
import { secondaryButton } from "../ui/styles";

export function Layout({ children }: { children: ReactNode }) {
  const me = useCurrentUser();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  async function logout() {
    await api<void>("/auth/logout", { method: "POST" });
    queryClient.clear();
    navigate("/login", { replace: true });
  }

  const links = [{ to: "/", label: "Home" }];
  if (me.role === "hospital_doctor") links.push({ to: "/queue/doctor", label: "Doctor queue" }, { to: "/setup", label: "Device setup" });
  if (me.role === "nsu_reviewer" || me.role === "admin") links.push({ to: "/queue/nsu", label: "NSU queue" });

  return (
    <OutboxProvider>
      <div className="min-h-screen">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
            <span className="font-semibold">AMCGH Data Capture</span>
            <nav className="flex flex-wrap gap-3 text-sm">
              {links.map((link) => (
                <NavLink key={link.to} to={link.to} end className={({ isActive }) => (isActive ? "font-semibold text-blue-700" : "text-slate-700 hover:text-blue-700")}>
                  {link.label}
                </NavLink>
              ))}
            </nav>
            <OutboxCount />
            <span className="ml-auto text-sm text-slate-600">
              {me.name} · {ROLE_LABEL[me.role]}
            </span>
            <button type="button" onClick={logout} className={secondaryButton}>
              Log out
            </button>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </div>
    </OutboxProvider>
  );
}

function OutboxCount() {
  const { items } = useOutbox();
  const waiting = items.filter((item) => !item.failed).length;
  return waiting > 0 ? <span className="text-sm font-medium text-amber-700">{waiting} waiting to upload</span> : null;
}
