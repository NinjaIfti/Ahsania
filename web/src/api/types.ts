export type Role = "uploader" | "hospital_doctor" | "nsu_reviewer" | "admin";
export type Status = "processing" | "quarantined" | "draft" | "pending_doctor" | "pending_nsu" | "approved";

export interface Me {
  id: number;
  name: string;
  email: string;
  role: Role;
  institution: "AMCGH" | "NSU";
}

export interface Option {
  value: string;
  synonyms: string[];
}

interface FieldBase {
  key: string;
  label?: string;
  hint?: string;
  required: boolean;
  source?: "dicom";
}
export type TextFieldDef = FieldBase & { type: "text" };
export type NumberFieldDef = FieldBase & { type: "number"; unit?: string; min?: number; max?: number };
export type DateFieldDef = FieldBase & { type: "date"; document_date?: boolean };
export type EnumFieldDef = FieldBase & { type: "enum"; options: Option[] };
export type BooleanFieldDef = FieldBase & { type: "boolean" };
export type GroupFieldDef = FieldBase & { type: "group"; repeat: boolean; fields: FieldDef[] };
export type FieldDef = TextFieldDef | NumberFieldDef | DateFieldDef | EnumFieldDef | BooleanFieldDef | GroupFieldDef;

export interface TemplateDef {
  key: string;
  version: number;
  phase: 1 | 2 | 3;
  kind: "document" | "film_photo" | "dicom";
  title: string;
  fields: FieldDef[];
}

export interface TemplateOut {
  key: string;
  version: number;
  phase: number;
  kind: TemplateDef["kind"];
  title: string;
  definition: TemplateDef;
  locked: boolean;
}

export interface FieldError {
  path: string;
  message: string;
}

export interface LastEvent {
  action: string;
  comment: string | null;
  actor_name: string;
  created_at: string;
}

/** NSU roles receive only `path`; hospital roles also get `old` and `new`. */
export interface FieldChange {
  path: string;
  old?: unknown;
  new?: unknown;
}

export interface EventOut extends LastEvent {
  id: number;
  field_changes: FieldChange[] | null;
  field_flags: Record<string, string> | null;
}

export interface FileOut {
  id: string;
  kind: "page" | "dicom";
  page_no: number | null;
  size: number;
}

export type AiColour = "green" | "amber" | "red" | "grey";

/** Where a value was read on a page: box = [x0, y0, x1, y1] in the stored page's pixels. */
export interface SourceBox {
  page: number;
  box: [number, number, number, number];
}

/** The AI's result for one field. `value` (what the AI filled in) is sent to hospital roles only. */
export interface AiField {
  colour: AiColour;
  confidence: number | null;
  sources: SourceBox[];
  edited: boolean;
  value?: unknown;
}

export interface Extraction {
  model: string;
  fields: Record<string, AiField>;
}

export interface QuarantineHit extends SourceBox {
  kind: string;
}

/** Why the safety net held a record back. Names kinds and pages, never the text that was found. */
export interface Quarantine {
  at: string;
  summary: string;
  hits: QuarantineHit[];
  files_expired: boolean;
}

export interface RecordSummary {
  id: string;
  study_code: string;
  template_key: string;
  template_title: string;
  template_version: number;
  status: Status;
  extraction_status: string;
  document_date: string | null;
  created_by_id: number;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  last_event: LastEvent | null;
  /** AI fields still holding an amber / red value (the queue's 🟡/🔴 counts). */
  ai_amber: number;
  ai_red: number;
}

export interface RecordDetail extends RecordSummary {
  values: Record<string, unknown>;
  extraction: Extraction | null;
  quarantine: Quarantine | null;
  extraction_queued_at: string | null;
  row_version: number;
  files: FileOut[];
  events: EventOut[];
  template: TemplateOut;
  errors: FieldError[];
  duplicate_of: string[];
}
