// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { burnRedactions } from "../imaging/render";
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
vi.mock("../imaging/render", () => ({ burnRedactions: vi.fn(async (blob: Blob) => blob) }));

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

function Harness({ onUpload }: { onUpload: (redacted: Blob[]) => Promise<void> }) {
  const [pages, setPages] = useState<PageDraft[]>([draft("p1"), draft("p2")]);
  return <RedactStep pages={pages} onChange={setPages} onUpload={onUpload} onBack={() => undefined} />;
}

afterEach(cleanup);

async function openEveryPageAndConfirm() {
  const checkbox = screen.getByLabelText("All names and numbers are covered.") as HTMLInputElement;
  await userEvent.click(screen.getByRole("button", { name: /^Page 2/ }));
  await waitFor(() => expect(checkbox.disabled).toBe(false));
  await userEvent.click(checkbox);
  return checkbox;
}

describe("RedactStep", () => {
  it("needs every page opened before upload, and unticks the confirmation when boxes change", async () => {
    render(<Harness onUpload={vi.fn(async () => {})} />);
    const checkbox = screen.getByLabelText("All names and numbers are covered.") as HTMLInputElement;
    const upload = screen.getByRole("button", { name: "Upload" }) as HTMLButtonElement;

    expect(checkbox.disabled).toBe(true);
    expect(screen.getByText("Open every page and check it before uploading.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Page 2 · 0 boxes · not checked" })).toBeTruthy();

    await openEveryPageAndConfirm();
    expect(upload.disabled).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Add box" }));
    expect(checkbox.checked).toBe(false);
    expect(upload.disabled).toBe(true);
  });

  it("burns the boxes in, hands only the redacted pages on, and shows a refusal", async () => {
    const onUpload = vi.fn(async () => {
      throw new Error("Upload refused: wrong key");
    });
    render(<Harness onUpload={onUpload} />);
    await openEveryPageAndConfirm();
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(vi.mocked(burnRedactions)).toHaveBeenCalledTimes(2);
    expect(onUpload).toHaveBeenCalledWith([expect.any(Blob), expect.any(Blob)]);
    expect((await screen.findByRole("alert")).textContent).toBe("Upload refused: wrong key");
  });
});
