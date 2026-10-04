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
}

export interface RecordDetail extends RecordSummary {
  values: Record<string, unknown>;
  extraction: unknown;
  row_version: number;
  files: FileOut[];
  events: EventOut[];
  template: TemplateOut;
  errors: FieldError[];
  duplicate_of: string[];
}
