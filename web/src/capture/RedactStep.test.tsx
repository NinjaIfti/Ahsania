// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { OutboxMeta } from "../storage/idb";
import { RedactStep } from "./RedactStep";
import type { PageDraft } from "./types";

vi.mock("../redaction/ocr", () => ({ ocrLines: vi.fn(async () => []) }));
vi.mock("./RedactionCanvas", () => ({
  RedactionCanvas: (props: { url: string; onShown: () => void }) => {
    useEffect(() => {
      props.onShown();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [props.url]);
    return <div data-testid="canvas">{props.url}</div>;
  },
}));
vi.mock("../outbox/OutboxContext", () => ({
  useOutbox: () => ({ items: [], othersWaiting: 0, refresh: vi.fn(), flush: vi.fn(), discard: vi.fn() }),
}));
vi.mock("../imaging/render", () => ({ burnRedactions: vi.fn(async (blob: Blob) => blob) }));
vi.mock("../outbox/outbox", () => ({ enqueue: vi.fn(), flushOutbox: vi.fn() }));
vi.mock("../auth/RequireAuth", () => ({
  useCurrentUser: () => ({ id: 1, name: "Demo Uploader", email: "uploader@amcgh.test", role: "uploader", institution: "AMCGH" }),
}));

const META: OutboxMeta = { study_code: "AMH-N0ZDG4KM8V", template_key: "radiology_report", key_fingerprint: "K-B9FF" };
const draft = (id: string): PageDraft => ({
  id,
  blob: new Blob(["x"], { type: "image/jpeg" }),
  url: `blob:${id}`,
  width: 1000,
  height: 1400,
  blur: 100,
  boxes: [],
  ocrDone: true,
});

function Harness() {
  const [pages, setPages] = useState<PageDraft[]>([draft("p1"), draft("p2")]);
  return <RedactStep pages={pages} onChange={setPages} meta={META} onBack={() => undefined} />;
}

afterEach(cleanup);

describe("RedactStep", () => {
  it("needs every page opened before upload, and unticks the confirmation when boxes change", async () => {
    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );
    const checkbox = screen.getByLabelText("All names and numbers are covered.") as HTMLInputElement;
    const upload = screen.getByRole("button", { name: "Upload" }) as HTMLButtonElement;

    expect(checkbox.disabled).toBe(true);
    expect(screen.getByText("Open every page and check it before uploading.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Page 2 · 0 boxes · not checked" })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /^Page 2/ }));
    await waitFor(() => expect(checkbox.disabled).toBe(false));

    await userEvent.click(checkbox);
    expect(upload.disabled).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Add box" }));
    expect(checkbox.checked).toBe(false);
    expect(upload.disabled).toBe(true);
  });
});
