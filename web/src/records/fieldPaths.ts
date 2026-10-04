export type PathPart = string | number;

/** ["lesions", 0, "lobe"] -> "lesions[0].lobe" (the server's error-path format). */
export function pathToString(parts: PathPart[]): string {
  return parts.reduce<string>((acc, part) => (typeof part === "number" ? `${acc}[${part}]` : acc ? `${acc}.${part}` : part), "");
}

export function getIn(obj: unknown, parts: PathPart[]): unknown {
  return parts.reduce<unknown>((current, part) => (current == null ? undefined : (current as Record<PathPart, unknown>)[part]), obj);
}

export function setIn<T>(obj: T, parts: PathPart[], value: unknown): T {
  if (parts.length === 0) return value as T;
  const [head, ...rest] = parts;
  if (typeof head === "number") {
    const list = Array.isArray(obj) ? [...obj] : [];
    list[head] = setIn(list[head], rest, value);
    return list as T;
  }
  const record = obj && typeof obj === "object" && !Array.isArray(obj) ? { ...(obj as Record<string, unknown>) } : {};
  record[head] = setIn(record[head], rest, value);
  return record as T;
}

export function humanize(key: string): string {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
