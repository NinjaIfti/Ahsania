// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import type { AiField, Extraction } from "../api/types";
import type { FieldDef } from "../api/types";
import { FormRenderer } from "./FormRenderer";

const FIELDS: FieldDef[] = [
  { key: "modality", label: "Modality", type: "enum", required: true, options: [{ value: "CT", synonyms: [] }, { value: "MRI", synonyms: [] }] },
  {
    key: "lesions",
    label: "Lesion",
    type: "group",
    repeat: true,
    required: false,
    fields: [{ key: "long_axis_cm", label: "Long axis", type: "number", unit: "cm", required: false }],
  },
];

function Harness({ onValues }: { onValues: (v: Record<string, unknown>) => void }) {
  const [values, setValues] = useState<Record<string, unknown>>({});
  return (
    <FormRenderer
      fields={FIELDS}
      values={values}
      onChange={(v) => {
        setValues(v);
        onValues(v);
      }}
      errors={{}}
      readOnly={false}
    />
  );
}

afterEach(cleanup);

describe("FormRenderer", () => {
  it("adds a repeat-group item and keeps a trailing dot while typing", async () => {
    let latest: Record<string, unknown> = {};
    render(<Harness onValues={(v) => (latest = v)} />);
    await userEvent.click(screen.getByRole("button", { name: "Add lesion" }));
    const input = screen.getByLabelText(/Long axis/) as HTMLInputElement;
    await userEvent.type(input, "2.");
    expect(input.value).toBe("2.");
    await userEvent.type(input, "3");
    expect(latest).toEqual({ lesions: [{ long_axis_cm: 2.3 }] });
  });

  it("passes text that is not a number on unchanged so the server can flag it", async () => {
    let latest: Record<string, unknown> = {};
    render(<Harness onValues={(v) => (latest = v)} />);
    await userEvent.click(screen.getByRole("button", { name: "Add lesion" }));
    await userEvent.type(screen.getByLabelText(/Long axis/), "2,3");
    expect(latest).toEqual({ lesions: [{ long_axis_cm: "2,3" }] });
  });

  it("stores null when an option is cleared", async () => {
    let latest: Record<string, unknown> = {};
    render(<Harness onValues={(v) => (latest = v)} />);
    await userEvent.selectOptions(screen.getByLabelText(/Modality/), "CT");
    expect(latest).toEqual({ modality: "CT" });
    await userEvent.selectOptions(screen.getByLabelText(/Modality/), "");
    expect(latest).toEqual({ modality: null });
  });

  it("removes a repeat-group item", async () => {
    let latest: Record<string, unknown> = {};
    render(<Harness onValues={(v) => (latest = v)} />);
    await userEvent.click(screen.getByRole("button", { name: "Add lesion" }));
    await userEvent.click(screen.getByRole("button", { name: "Add lesion" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove lesion 1" }));
    expect(latest).toEqual({ lesions: [{}] });
  });

  it("shows server errors and reviewer flags under the right field", () => {
    render(
      <FormRenderer
        fields={FIELDS}
        values={{ lesions: [{}] }}
        onChange={() => {}}
        errors={{ "lesions[0].long_axis_cm": "must be at most 20" }}
        flags={{ modality: "Check against page 1" }}
        readOnly={false}
      />,
    );
    expect(screen.getByText("must be at most 20")).toBeTruthy();
    expect(screen.getByText("Reviewer: Check against page 1")).toBeTruthy();
  });

  it("disables inputs and hides add/remove when read-only", () => {
    render(<FormRenderer fields={FIELDS} values={{ lesions: [{}] }} onChange={() => {}} errors={{}} readOnly />);
    expect(screen.queryByRole("button", { name: "Add lesion" })).toBeNull();
    expect((screen.getByLabelText(/Long axis/) as HTMLInputElement).disabled).toBe(true);
  });

  it.each(["Infinity", "0x10", "1e3"])("keeps %s as text so the server can flag it", async (typed) => {
    let latest: Record<string, unknown> = {};
    render(<Harness onValues={(v) => (latest = v)} />);
    await userEvent.click(screen.getByRole("button", { name: "Add lesion" }));
    await userEvent.type(screen.getByLabelText(/Long axis/), typed);
    expect(latest).toEqual({ lesions: [{ long_axis_cm: typed }] });
  });
});

describe("FormRenderer AI markers", () => {
  const extraction: Extraction = {
    model: "m",
    fields: { modality: { colour: "amber", confidence: 0.6, sources: [{ page: 1, box: [1, 2, 3, 4] }], edited: false, value: "CT" } },
  };

  it("marks a field the AI filled, reports its sources on focus, and drops the mark once changed", async () => {
    const focused: Array<[string, AiField | null]> = [];
    function AiHarness() {
      const [values, setValues] = useState<Record<string, unknown>>({ modality: "CT" });
      return (
        <FormRenderer
          fields={FIELDS}
          values={values}
          onChange={setValues}
          errors={{}}
          readOnly={false}
          extraction={extraction}
          onFieldFocus={(path, ai) => focused.push([path, ai])}
        />
      );
    }
    const { container } = render(<AiHarness />);
    expect(container.querySelector('[data-ai="amber"]')).not.toBeNull();
    expect(screen.getByText("AI: please check")).toBeTruthy();
    const select = screen.getByLabelText(/Modality/);
    await userEvent.click(select);
    expect(focused.at(-1)).toEqual(["modality", extraction.fields.modality]);
    await userEvent.selectOptions(select, "MRI");
    expect(container.querySelector("[data-ai]")).toBeNull();
  });

  it("lets a read-only reviewer tap a field to see its sources", async () => {
    const focused: string[] = [];
    render(
      <FormRenderer fields={FIELDS} values={{ modality: "CT" }} onChange={() => {}} errors={{}} readOnly extraction={extraction} onFieldFocus={(path) => focused.push(path)} />,
    );
    await userEvent.click(screen.getByText("AI: please check"));
    expect(focused).toContain("modality");
  });
});
