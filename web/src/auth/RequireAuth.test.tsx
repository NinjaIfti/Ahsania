// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../api/types";
import { RequireAuth } from "./RequireAuth";

const ME: Me = { id: 1, name: "Demo Uploader", email: "uploader@amcgh.test", role: "uploader", institution: "AMCGH" };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RequireAuth", () => {
  it("keeps the app mounted when a background refetch of /me fails", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["me"], ME);
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <RequireAuth>
            <p>inside</p>
          </RequireAuth>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await act(() => client.refetchQueries({ queryKey: ["me"] }));
    expect(client.getQueryState(["me"])?.status).toBe("error"); // the refetch failed, the old data is kept
    await act(() => new Promise((resolve) => setTimeout(resolve, 20))); // let the observers re-render
    expect(screen.getByText("inside")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
