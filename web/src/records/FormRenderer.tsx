import { useEffect, useState } from "react";
import type { FieldDef } from "../api/types";
import { card, inputClass, secondaryButton } from "../ui/styles";
import { getIn, humanize, pathToString, setIn, type PathPart } from "./fieldPaths";

interface Props {
  fields: FieldDef[];
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  errors: Record<string, string>;
  readOnly: boolean;
  flags?: Record<string, string>;
}

interface Context {
  values: Record<string, unknown>;
  set: (parts: PathPart[], value: unknown) => void;
  errors: Record<string, string>;
  flags: Record<string, string>;
  readOnly: boolean;
}

export function FormRenderer({ fields, values, onChange, errors, readOnly, flags = {} }: Props) {
  const ctx: Context = { values, set: (parts, value) => onChange(setIn(values, parts, value)), errors, flags, readOnly };
  return (
    <div className="space-y-4">
      {fields.map((field) => (
        <FieldView key={field.key} field={field} parts={[field.key]} ctx={ctx} />
      ))}
    </div>
  );
}

function FieldView({ field, parts, ctx }: { field: FieldDef; parts: PathPart[]; ctx: Context }) {
  const path = pathToString(parts);
  const value = getIn(ctx.values, parts);
  const label = field.label ?? humanize(field.key);
  const error = ctx.errors[path];
  const flag = ctx.flags[path];
  const readOnly = ctx.readOnly || field.source === "dicom";

  if (field.type === "group") {
    if (!field.repeat) {
      return (
        <fieldset className={`${card} space-y-3`}>
          <legend className="px-1 font-medium">{label}</legend>
          {field.fields.map((sub) => (
            <FieldView key={sub.key} field={sub} parts={[...parts, sub.key]} ctx={ctx} />
          ))}
        </fieldset>
      );
    }
    const items = Array.isArray(value) ? value : [];
    return (
      <fieldset className="space-y-3">
        <legend className="font-medium">
          {label} ({items.length})
        </legend>
        {items.map((_, i) => (
          <div key={i} className={`${card} space-y-3`}>
            <div className="flex items-center justify-between">
              <span className="font-medium">
                {label} {i + 1}
              </span>
              {!readOnly && (
                <button type="button" onClick={() => ctx.set(parts, items.filter((__, j) => j !== i))} className={secondaryButton}>
                  Remove {label.toLowerCase()} {i + 1}
                </button>
              )}
            </div>
            {field.fields.map((sub) => (
              <FieldView key={sub.key} field={sub} parts={[...parts, i, sub.key]} ctx={ctx} />
            ))}
          </div>
        ))}
        {!readOnly && (
          <button type="button" onClick={() => ctx.set(parts, [...items, {}])} className={secondaryButton}>
            Add {label.toLowerCase()}
          </button>
        )}
        {error && <p className="text-sm text-red-700">{error}</p>}
      </fieldset>
    );
  }

  const id = `f-${path}`;
  const inputCls = `${inputClass} ${error ? "border-red-500" : ""}`;
  const set = (v: unknown) => ctx.set(parts, v);
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
        {field.required && <span className="text-red-700"> *</span>}
        {field.type === "number" && field.unit && <span className="text-slate-500"> ({field.unit})</span>}
      </label>
      {field.type === "text" && (
        <textarea id={id} rows={2} disabled={readOnly} value={typeof value === "string" ? value : ""} onChange={(e) => set(e.target.value === "" ? null : e.target.value)} className={inputCls} />
      )}
      {field.type === "number" && <NumberInput id={id} value={value} disabled={readOnly} onChange={set} className={inputCls} />}
      {field.type === "date" && (
        <input id={id} type="date" disabled={readOnly} value={typeof value === "string" ? value : ""} onChange={(e) => set(e.target.value || null)} className={inputCls} />
      )}
      {field.type === "enum" && (
        <select id={id} disabled={readOnly} value={typeof value === "string" ? value : ""} onChange={(e) => set(e.target.value || null)} className={inputCls}>
          <option value="">—</option>
          {field.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.value}
            </option>
          ))}
        </select>
      )}
      {field.type === "boolean" && (
        <select
          id={id}
          disabled={readOnly}
          value={value === true ? "yes" : value === false ? "no" : ""}
          onChange={(e) => set(e.target.value === "yes" ? true : e.target.value === "no" ? false : null)}
          className={inputCls}
        >
          <option value="">—</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </select>
      )}
      {field.hint && <p className="mt-1 text-xs text-slate-500">{field.hint}</p>}
      {flag && <p className="mt-1 text-sm text-amber-700">Reviewer: {flag}</p>}
      {error && <p className="mt-1 text-sm text-red-700">{error}</p>}
    </div>
  );
}

const DECIMAL = /^[-+]?(\d+\.?\d*|\.\d+)$/;

/** "" -> null, plain decimal text -> number, anything else stays text so the server can flag it. */
function parseNumber(text: string): unknown {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  return DECIMAL.test(trimmed) ? Number(trimmed) : text;
}

function display(value: unknown): string {
  return typeof value === "number" || typeof value === "string" ? String(value) : "";
}

function NumberInput({ id, value, disabled, onChange, className }: { id: string; value: unknown; disabled: boolean; onChange: (v: unknown) => void; className: string }) {
  const [text, setText] = useState(display(value));
  useEffect(() => {
    // Only resync when the stored value changed from outside (e.g. a reload), never while typing "2." -> 2.
    if (parseNumber(text) !== value && !(value === undefined && text === "")) setText(display(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input
      id={id}
      type="text"
      inputMode="decimal"
      disabled={disabled}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onChange(parseNumber(e.target.value));
      }}
      className={className}
    />
  );
}
