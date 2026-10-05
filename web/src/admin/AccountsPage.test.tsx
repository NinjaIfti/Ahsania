// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Account, Me } from "../api/types";
import AccountsPage from "./AccountsPage";

const ADMIN: Me = { id: 1, name: "Demo Admin", username: "admin", role: "admin" };
const state: { me: Me } = { me: ADMIN };
vi.mock("../auth/RequireAuth", () => ({ useCurrentUser: () => state.me }));

let accounts: Account[];
let posted: unknown[];

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  state.me = ADMIN;
  posted = [];
  accounts = [
    { id: 1, name: "Demo Admin", username: "admin", role: "admin", active: true },
    { id: 2, name: "Demo Doctor", username: "doctor", role: "doctor", active: true },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/admin/users" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        posted.push(body);
        if (body.username === "doctor") return reply(409, { detail: "That ID is already taken" });
        const created = { id: 3, name: body.name, username: body.username, role: body.role, active: true };
        accounts = [...accounts, created];
        return reply(201, created);
      }
      return reply(200, accounts);
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AccountsPage />
    </QueryClientProvider>,
  );
}

describe("AccountsPage", () => {
  it("lists accounts and offers no Deactivate on the admin's own row", async () => {
    renderPage();
    const own = (await screen.findByText("admin")).closest("tr")!;
    const other = screen.getByText("doctor").closest("tr")!;
    expect(within(own).queryByRole("button", { name: "Deactivate" })).toBeNull();
    expect(within(other).getByRole("button", { name: "Deactivate" })).toBeTruthy();
  });

  it("creates a doctor account and shows it", async () => {
    renderPage();
    await screen.findByText("doctor");
    await userEvent.type(screen.getByLabelText("Name"), "Dr. Rahman");
    await userEvent.type(screen.getByLabelText("ID"), "dr.rahman");
    await userEvent.type(screen.getByLabelText("Password"), "long-enough-1");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("dr.rahman")).toBeTruthy();
    expect(posted).toEqual([{ name: "Dr. Rahman", username: "dr.rahman", password: "long-enough-1", role: "doctor" }]);
  });

  it("shows the server's reason when the ID is taken", async () => {
    renderPage();
    await screen.findByText("doctor");
    await userEvent.type(screen.getByLabelText("Name"), "Someone");
    await userEvent.type(screen.getByLabelText("ID"), "doctor");
    await userEvent.type(screen.getByLabelText("Password"), "long-enough-1");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("That ID is already taken")).toBeTruthy();
  });

  it("is for admins only", () => {
    state.me = { id: 2, name: "Demo Doctor", username: "doctor", role: "doctor" };
    renderPage();
    expect(screen.getByText("Only an admin can manage accounts.")).toBeTruthy();
  });
});
