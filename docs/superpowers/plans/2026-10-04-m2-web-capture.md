# M2 — Web Capture App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React web app in which hospital staff turn a registration number into a study code, photograph and crop a document, black out names on the phone, upload it, fill the form by hand, and send it through doctor and NSU approval. There is no AI yet.

**Architecture:** A Vite + React + TypeScript single-page app in `web/`, talking to the M1 API under `/api` (Vite proxies to `127.0.0.1:8000` in development). Privacy-critical work runs only in the browser: the HMAC study code (WebCrypto), Tesseract.js redaction hints, and burning the boxes in on a canvas. Pure logic lives in small tested modules (`crypto/`, `imaging/`, `redaction/labels.ts`, `outbox/outbox.ts`, `records/fieldPaths.ts`, `records/permissions.ts`). Screens are tested end-to-end with Playwright against the real dev server.

**Tech Stack:** React 19, Vite, TypeScript, React Router 7, TanStack Query 5, Tailwind CSS 4, react-konva, react-zoom-pan-pinch, Tesseract.js 7 (self-hosted), idb, Vitest (+ jsdom, Testing Library, fake-indexeddb), Playwright.

**Spec:** `docs/superpowers/specs/2026-10-04-data-capture-design.md` (milestone M2 of §13). **Depends on:** M1 being complete (`docs/superpowers/plans/2026-10-04-m1-server-core.md`). The e2e tests start the M1 dev server with `uv run --project ../server python -m capture.devserver --reset`.

## Global Constraints

- The app must be served over **HTTPS or from localhost/127.0.0.1**, because WebCrypto and `crypto.randomUUID` need a secure context.
- **No third-party scripts, fonts or CDNs.** Tesseract.js worker, core and `eng` language data are copied to `public/tesseract/` by `scripts/copy-tesseract.mjs` (run on `npm install`) and loaded from `/tesseract/…`.
- **The registration number is never sent or stored.** It is cleared from state as soon as the study code is computed.
- **Unredacted images are never persisted.** They live only in component memory. The outbox (IndexedDB) stores redacted JPEG bytes only.
- **Study code** = `"AMH-" + first 10 chars of CrockfordBase32(HMAC-SHA256(key, normalized))`, where `normalized = uppercase(regNo)` with whitespace, `-`, `/` and `.` removed. Crockford alphabet: `0123456789ABCDEFGHJKMNPQRSTVWXYZ`.
- **Hospital key** = 32 random bytes shown as a 52-character Crockford string, printed in groups of 4 separated by `-`. It is stored as a **non-extractable** HMAC `CryptoKey` in IndexedDB database `amcgh-capture`, store `device`, key `"key"`, together with its fingerprint.
- **Fingerprint** = `"K-"` + first 4 hex chars (uppercase) of `SHA-256("amcgh-fingerprint:" + canonicalKeyString)`.
- **Redaction:** label list, verbatim from the spec: `Name, Patient, Pt, Mobile, Mob, Phone, Cell, Contact, Address, Addr, Father, Husband, Guardian, S/O, D/O, W/O, Reg, Registration, ID, MRN, UHID, NID`. Bangladeshi mobile numbers are also detected. Boxes are burned in as solid black; the final JPEG uses quality 0.85, long side ≤ 3000 px, and the re-encode strips EXIF.
- **UI copy from the spec, verbatim:** `Photo looks blurry — retake?` · `All names and numbers are covered.` · `Locked until Phase 3` · `Someone else changed this record — reload`.
- **Value paths** match the server exactly: `lesions[0].long_axis_cm`.
- Every commit ends with the trailer line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A number typed with a trailing dot or a comma** (`2.` on the way to `2.3`, or `2,3`) should not have the input reset under the user's fingers. Non-numbers are kept as text so the server flags them. Pinned in Task 8 (unit) and Task 9 (e2e).
2. **Upload while offline, or the server returns 5xx or 401** (expired session): the redacted item stays in the outbox and retries. Overlapping flushes never send it twice. Pinned in Task 5.
3. **Hospital key typed by hand** with lowercase, dashes, or `O`/`0` and `I`/`L`/`1` confusion should be accepted. A typo should show the expected fingerprint. Pinned in Tasks 1 and 3.
4. **The same registration number written differently** (`AMH-00123`, `amh 00123`, `AMH/00123.`) should give the same study code. Pinned in Task 1.
5. **A refused upload** (wrong device key, locked form) should stay visible on the home screen with the server's reason and a Discard button, not loop forever. Pinned in Task 5 (unit) and Task 10 (home screen).

## File Map

```
web/
  package.json  tsconfig.json  vite.config.ts  index.html  playwright.config.ts
  scripts/copy-tesseract.mjs            copies Tesseract assets into public/tesseract   Task 1
  e2e/flow.spec.ts                       one serial end-to-end story, grown per task    Tasks 2–10
  e2e/fixtures/make_report.py, report.jpg   synthetic report photo (made-up patient)    Task 6
  src/
    main.tsx  App.tsx  index.css
    crypto/base32.ts  deviceKey.ts  studyCode.ts  keyStore.ts  keySetup.ts            Tasks 1, 3
    storage/idb.ts                       IndexedDB schema (device key + outbox)        Task 3
    api/types.ts  client.ts  hooks.ts                                                  Task 2
    auth/LoginPage.tsx  RequireAuth.tsx  roles.ts                                      Task 2
    layout/Layout.tsx                                                                  Tasks 2, 5
    ui/styles.ts  StatusBadge.tsx  time.ts                                             Tasks 2, 9, 10
    device/DeviceSetupPage.tsx                                                         Task 3
    imaging/geometry.ts  blur.ts  render.ts  useHtmlImage.ts                           Tasks 4, 7
    redaction/labels.ts  ocr.ts                                                        Task 4
    outbox/outbox.ts  OutboxContext.tsx                                                Task 5
    capture/CapturePage.tsx  PatientStep.tsx  TemplateStep.tsx  PhotosStep.tsx
    capture/CropEditor.tsx  RedactStep.tsx  RedactionCanvas.tsx  types.ts              Tasks 6–7
    records/fieldPaths.ts  permissions.ts  FormRenderer.tsx                            Task 8
    records/RecordPage.tsx  PageViewer.tsx  RecordList.tsx                             Tasks 9–10
    home/HomePage.tsx   queues/QueuePage.tsx                                           Tasks 2, 10
```

---

### Task 1: Web project and the study-code cryptography

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/index.html`, `web/scripts/copy-tesseract.mjs`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/index.css`, `web/src/crypto/base32.ts`, `web/src/crypto/deviceKey.ts`, `web/src/crypto/studyCode.ts`
- Test: `web/src/crypto/crypto.test.ts`

**Interfaces:**
- Produces:
  - `base32.ts`: `CROCKFORD`, `encodeCrockford(bytes)`, `decodeCrockford(text, byteLength)`. Decoding throws `The key must be N characters (ignoring dashes)` or `Invalid character "X" in key`.
  - `deviceKey.ts`: `KEY_BYTES = 32`, `generateKeyString()`, `canonicalKeyString(input)`, `formatKeyForPrint(key)`, `fingerprintOf(keyString): Promise<string>`, `importHmacKey(keyString): Promise<CryptoKey>` (non-extractable).
  - `studyCode.ts`: `STUDY_CODE_RE`, `normalizeRegNo(regNo)`, `studyCodeFor(key: CryptoKey, regNo): Promise<string>`, which throws `Enter the registration number` on empty input.

- [ ] **Step 1: Create the project files**

`web/package.json`:

```json
{
  "name": "amcgh-capture-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "typecheck": "tsc",
    "test": "vitest run",
    "e2e": "playwright test",
    "postinstall": "node scripts/copy-tesseract.mjs"
  }
}
```

`web/scripts/copy-tesseract.mjs`:

```js
// Copies Tesseract.js worker, WASM cores and English data into public/tesseract so nothing loads from a CDN.
import { cpSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dest = fileURLToPath(new URL("../public/tesseract/", import.meta.url));

let tesseractDir;
try {
  tesseractDir = dirname(require.resolve("tesseract.js/package.json"));
} catch {
  console.log("tesseract.js not installed yet — skipping asset copy");
  process.exit(0);
}
const coreDir = dirname(require.resolve("tesseract.js-core/package.json"));
const langFile = join(dirname(require.resolve("@tesseract.js-data/eng/package.json")), "4.0.0", "eng.traineddata.gz");
if (!existsSync(langFile)) throw new Error(`missing ${langFile}`);

mkdirSync(join(dest, "core"), { recursive: true });
mkdirSync(join(dest, "lang"), { recursive: true });
cpSync(join(tesseractDir, "dist", "worker.min.js"), join(dest, "worker.min.js"));
for (const file of readdirSync(coreDir).filter((f) => f.endsWith(".wasm.js"))) {
  cpSync(join(coreDir, file), join(dest, "core", file));
}
cpSync(langFile, join(dest, "lang", "eng.traineddata.gz"));
console.log(`tesseract assets copied to ${dest}`);
```

`web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "types": ["vite/client", "node"]
  },
  "include": ["src", "e2e", "vite.config.ts", "playwright.config.ts"]
}
```

`web/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { include: ["src/**/*.test.{ts,tsx}"], environment: "node" },
});
```

`web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AMCGH Data Capture</title>
  </head>
  <body class="bg-slate-50 text-slate-900">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`web/src/index.css`:

```css
@import "tailwindcss";
```

`web/src/main.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
```

`web/src/App.tsx` (Task 2 replaces it):

```tsx
export default function App() {
  return <h1 className="p-6 text-2xl font-semibold">AMCGH Data Capture</h1>;
}
```

- [ ] **Step 2: Install dependencies**

Run:

```bash
cd web
npm install react react-dom react-router @tanstack/react-query idb konva react-konva react-zoom-pan-pinch tesseract.js @tesseract.js-data/eng
npm install -D vite @vitejs/plugin-react typescript @types/react @types/react-dom @types/node tailwindcss @tailwindcss/vite vitest jsdom @testing-library/react @testing-library/dom @testing-library/user-event fake-indexeddb @playwright/test
ls public/tesseract public/tesseract/core public/tesseract/lang
```

Expected: the output ends with `tesseract assets copied to …`. The listing shows `worker.min.js`, several `tesseract-core-*.wasm.js` files and `eng.traineddata.gz`.

- [ ] **Step 3: Write the failing tests**

`web/src/crypto/crypto.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { decodeCrockford, encodeCrockford } from "./base32";
import { canonicalKeyString, fingerprintOf, formatKeyForPrint, importHmacKey } from "./deviceKey";
import { STUDY_CODE_RE, normalizeRegNo, studyCodeFor } from "./studyCode";

// Reference values computed independently with Python's hmac/hashlib.
const BYTES_0_31 = Uint8Array.from({ length: 32 }, (_, i) => i);
const KEY = "000G40R40M30E209185GR38E1W8124GK2GAHC5RR34D1P70X3RFG";
const KEY_FF = "Z".repeat(51) + "G";

describe("Crockford base32", () => {
  it("encodes 32 bytes as 52 characters", () => {
    expect(encodeCrockford(BYTES_0_31)).toBe(KEY);
    expect(encodeCrockford(new Uint8Array(32).fill(255))).toBe(KEY_FF);
  });
  it("round-trips", () => {
    expect(Array.from(decodeCrockford(KEY, 32))).toEqual(Array.from(BYTES_0_31));
  });
  it("accepts lowercase, dashes and look-alike letters when a key is typed", () => {
    const typed = formatKeyForPrint(KEY).toLowerCase().replace(/1/g, "l").replace(/0/g, "o");
    expect(canonicalKeyString(typed)).toBe(KEY);
  });
  it("rejects a key of the wrong length", () => {
    expect(() => canonicalKeyString(KEY.slice(0, 51))).toThrow("The key must be 52 characters (ignoring dashes)");
  });
  it("rejects characters outside the alphabet", () => {
    expect(() => canonicalKeyString(KEY.slice(0, 51) + "U")).toThrow('Invalid character "U" in key');
  });
});

describe("fingerprint", () => {
  it("matches the reference values", async () => {
    expect(await fingerprintOf(KEY)).toBe("K-B9FF");
    expect(await fingerprintOf(KEY_FF)).toBe("K-786D");
  });
});

describe("study code", () => {
  it("normalizes registration numbers", () => {
    expect(normalizeRegNo(" amh-001/23. ")).toBe("AMH00123");
  });
  it.each([
    ["AMH-00123", "AMH-N0ZDG4KM8V"],
    ["amh 00123", "AMH-N0ZDG4KM8V"],
    ["AMH/00123.", "AMH-N0ZDG4KM8V"],
    ["12345/2026", "AMH-MHNZ0NHAA4"],
    ["A.B-C d", "AMH-0KWJ57170Y"],
  ])("%s -> %s", async (regNo, expected) => {
    const code = await studyCodeFor(await importHmacKey(KEY), regNo);
    expect(code).toBe(expected);
    expect(code).toMatch(STUDY_CODE_RE);
  });
  it("depends on the hospital key", async () => {
    expect(await studyCodeFor(await importHmacKey(KEY_FF), "AMH00123")).toBe("AMH-E6RRNCP0BD");
  });
  it("refuses an empty registration number", async () => {
    await expect(studyCodeFor(await importHmacKey(KEY), " - ")).rejects.toThrow("Enter the registration number");
  });
  it("keeps the imported key non-extractable", async () => {
    expect((await importHmacKey(KEY)).extractable).toBe(false);
  });
});
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL with `Failed to resolve import "./base32"`.

- [ ] **Step 5: Implement the crypto modules**

`web/src/crypto/base32.ts`:

```ts
export const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function encodeCrockford(bytes: Uint8Array): string {
  let bits = 0;
  let value = 0;
  let out = "";
  for (const byte of bytes) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      out += CROCKFORD[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
    value &= (1 << bits) - 1;
  }
  if (bits > 0) out += CROCKFORD[(value << (5 - bits)) & 31];
  return out;
}

export function decodeCrockford(text: string, byteLength: number) {
  const clean = text.toUpperCase().replace(/[\s-]/g, "").replace(/[IL]/g, "1").replace(/O/g, "0");
  const expectedChars = Math.ceil((byteLength * 8) / 5);
  if (clean.length !== expectedChars) throw new Error(`The key must be ${expectedChars} characters (ignoring dashes)`);
  const out = new Uint8Array(byteLength);
  let bits = 0;
  let value = 0;
  let index = 0;
  for (const ch of clean) {
    const digit = CROCKFORD.indexOf(ch);
    if (digit < 0) throw new Error(`Invalid character "${ch}" in key`);
    value = (value << 5) | digit;
    bits += 5;
    if (bits >= 8) {
      if (index < byteLength) out[index++] = (value >>> (bits - 8)) & 255;
      bits -= 8;
      value &= (1 << bits) - 1;
    }
  }
  return out;
}
```

`web/src/crypto/deviceKey.ts`:

```ts
import { decodeCrockford, encodeCrockford } from "./base32";

export const KEY_BYTES = 32;

export function generateKeyString(): string {
  return encodeCrockford(crypto.getRandomValues(new Uint8Array(KEY_BYTES)));
}

/** Normalizes a typed key (case, dashes, O/0, I/L/1) to its 52-character form. */
export function canonicalKeyString(input: string): string {
  return encodeCrockford(decodeCrockford(input, KEY_BYTES));
}

export function formatKeyForPrint(key: string): string {
  return (key.match(/.{1,4}/g) ?? []).join("-");
}

export async function fingerprintOf(keyString: string): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`amcgh-fingerprint:${keyString}`)));
  const hex = Array.from(digest.slice(0, 2), (b) => b.toString(16).padStart(2, "0")).join("");
  return `K-${hex.toUpperCase()}`;
}

export function importHmacKey(keyString: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", decodeCrockford(keyString, KEY_BYTES), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
}
```

`web/src/crypto/studyCode.ts`:

```ts
import { encodeCrockford } from "./base32";

export const STUDY_CODE_RE = /^AMH-[0-9A-HJKMNP-TV-Z]{10}$/;

export function normalizeRegNo(regNo: string): string {
  return regNo.toUpperCase().replace(/[\s\-/.]/g, "");
}

export async function studyCodeFor(key: CryptoKey, regNo: string): Promise<string> {
  const normalized = normalizeRegNo(regNo);
  if (!normalized) throw new Error("Enter the registration number");
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(normalized)));
  return `AMH-${encodeCrockford(signature).slice(0, 10)}`;
}
```

- [ ] **Step 6: Run the tests and type-check**

Run: `cd web && npm test && npm run typecheck`
Expected: all crypto tests pass and `tsc` reports no errors.

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/package-lock.json web/tsconfig.json web/vite.config.ts web/index.html web/scripts web/src
git commit -m "feat(web): project scaffold and study-code cryptography" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: API client, login, layout and the end-to-end harness

**Files:**
- Create: `web/src/api/types.ts`, `web/src/api/client.ts`, `web/src/api/hooks.ts`, `web/src/auth/roles.ts`, `web/src/auth/RequireAuth.tsx`, `web/src/auth/LoginPage.tsx`, `web/src/ui/styles.ts`, `web/src/layout/Layout.tsx`, `web/src/home/HomePage.tsx`, `web/playwright.config.ts`, `web/e2e/flow.spec.ts`
- Replace: `web/src/App.tsx`
- Test: `web/src/api/client.test.ts`, `web/e2e/flow.spec.ts`

**Interfaces:**
- Consumes: the M1 API (`/api/auth/login`, `/api/auth/logout`, `/api/me`, `/api/templates`, `/api/records…`, `/api/device/fingerprint`).
- Produces:
  - `types.ts`: `Role`, `Status`, `Me`, `Option`, `FieldDef` (union of `TextFieldDef | NumberFieldDef | DateFieldDef | EnumFieldDef | BooleanFieldDef | GroupFieldDef`), `TemplateDef`, `TemplateOut`, `FieldError`, `LastEvent`, `FieldChange`, `EventOut`, `FileOut`, `RecordSummary`, `RecordDetail`.
  - `client.ts`: `ApiError(status, message)`, `errorMessage(status, body)`, `api<T>(path, init?)` (prefixes `/api`; JSON unless the body is `FormData`), `json(data)`.
  - `hooks.ts`: `useMe()` (`null` when logged out), `useTemplates()`, `useRecord(id)` (polls every 3 s while `processing`), `useRecords(filter, enabled = true)`, `useExpectedFingerprint(enabled)`.
  - `roles.ts`: `isHospital(role)`, `ROLE_LABEL`.
  - `RequireAuth`, `useCurrentUser(): Me`, `Layout`.
  - `styles.ts`: `inputClass`, `primaryButton`, `secondaryButton`, `card`.
  - `App.tsx` has an `AuthedRoutes` `<Routes>` block that later tasks add `<Route>`s to.
  - e2e helpers in `flow.spec.ts`: a shared `page`, plus `login(email)` and `logout()`.

- [ ] **Step 1: Write the failing tests**

`web/src/api/client.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { errorMessage } from "./client";

describe("errorMessage", () => {
  it("uses FastAPI's string detail", () => {
    expect(errorMessage(401, { detail: "Invalid email or password" })).toBe("Invalid email or password");
  });
  it("joins validation errors", () => {
    expect(errorMessage(422, { detail: [{ msg: "Field required" }, { msg: "String too short" }] })).toBe("Field required; String too short");
  });
  it("falls back to the status code", () => {
    expect(errorMessage(502, null)).toBe("Request failed (502)");
  });
});
```

`web/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  workers: 1,
  fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run --project ../server python -m capture.devserver --reset --port 8000",
      url: "http://127.0.0.1:8000/api/health",
      timeout: 180_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
```

`web/e2e/flow.spec.ts`. This is one story that runs in order on one browser page. Later tasks append tests to the end of this file.

```ts
import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "demo-pass-123";

test.describe.configure({ mode: "serial" });

let page: Page;
test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});
test.afterAll(async () => {
  await page.close();
});

async function login(email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
}

async function logout() {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

test("wrong password is refused; right password signs in and out", async () => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email").fill("uploader@amcgh.test");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Invalid email or password");
  await login("uploader@amcgh.test");
  await expect(page.getByText("Demo Uploader · Uploader")).toBeVisible();
  await logout();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL with `Failed to resolve import "./client"`.

Run: `cd web && npx playwright install chromium && npm run e2e`
Expected: FAIL. The page never redirects to `/login` because App only shows a heading.

- [ ] **Step 3: Implement the API layer**

`web/src/api/types.ts`:

```ts
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

export interface FieldChange {
  path: string;
  old: unknown;
  new: unknown;
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
```

`web/src/api/client.ts`:

```ts
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => (typeof d?.msg === "string" ? d.msg : String(d))).join("; ");
  return `Request failed (${status})`;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api${path}`, { credentials: "same-origin", ...init, headers });
  if (res.status === 204) return undefined as T;
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(res.status, body));
  return body as T;
}

export const json = (data: unknown): string => JSON.stringify(data);
```

`web/src/api/hooks.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "./client";
import type { Me, RecordDetail, RecordSummary, TemplateOut } from "./types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

export function useTemplates() {
  return useQuery({ queryKey: ["templates"], queryFn: () => api<TemplateOut[]>("/templates"), staleTime: 300_000 });
}

export function useRecord(id: string) {
  return useQuery({
    queryKey: ["record", id],
    queryFn: () => api<RecordDetail>(`/records/${id}`),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 3000 : false),
  });
}

export interface RecordFilter {
  status?: string;
  mine?: boolean;
  study_code?: string;
}

export function useRecords(filter: RecordFilter, enabled = true) {
  const params = new URLSearchParams();
  if (filter.status) params.set("status", filter.status);
  if (filter.mine) params.set("mine", "true");
  if (filter.study_code) params.set("study_code", filter.study_code);
  return useQuery({
    queryKey: ["records", filter],
    queryFn: () => api<RecordSummary[]>(`/records?${params}`),
    enabled,
  });
}

export function useExpectedFingerprint(enabled: boolean) {
  return useQuery({
    queryKey: ["fingerprint"],
    queryFn: () => api<{ expected: string | null }>("/device/fingerprint"),
    enabled,
  });
}
```

- [ ] **Step 4: Implement login, the auth guard, layout and home**

`web/src/ui/styles.ts`:

```ts
export const inputClass =
  "mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-base shadow-sm focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 disabled:bg-slate-100";
export const primaryButton =
  "inline-flex items-center justify-center rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50";
export const secondaryButton =
  "inline-flex items-center justify-center rounded-md border border-slate-300 bg-white px-4 py-2 font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
export const card = "rounded-lg border border-slate-200 bg-white p-4 shadow-sm";
```

`web/src/auth/roles.ts`:

```ts
import type { Role } from "../api/types";

export const ROLE_LABEL: Record<Role, string> = {
  uploader: "Uploader",
  hospital_doctor: "Hospital doctor",
  nsu_reviewer: "NSU reviewer",
  admin: "Admin",
};

export function isHospital(role: Role): boolean {
  return role === "uploader" || role === "hospital_doctor";
}
```

`web/src/auth/RequireAuth.tsx`:

```tsx
import type { ReactNode } from "react";
import { Navigate } from "react-router";
import { useMe } from "../api/hooks";
import type { Me } from "../api/types";

export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.isPending) return <p className="p-6">Loading…</p>;
  if (me.isError) return <p role="alert" className="p-6 text-red-700">Cannot reach the server: {me.error.message}</p>;
  if (!me.data) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** The signed-in user. Only call inside <RequireAuth>. */
export function useCurrentUser(): Me {
  const { data } = useMe();
  if (!data) throw new Error("useCurrentUser used outside RequireAuth");
  return data;
}
```

`web/src/auth/LoginPage.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api, json } from "../api/client";
import type { Me } from "../api/types";
import { card, inputClass, primaryButton } from "../ui/styles";

export default function LoginPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/login", { method: "POST", body: json({ email, password }) });
      queryClient.setQueryData(["me"], me);
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto mt-16 max-w-sm px-4">
      <h1 className="mb-6 text-center text-2xl font-semibold">AMCGH Data Capture</h1>
      <form onSubmit={submit} className={`${card} space-y-4`}>
        <label className="block">
          <span className="text-sm font-medium">Email</span>
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
        </label>
        <label className="block">
          <span className="text-sm font-medium">Password</span>
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
        </label>
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <button type="submit" disabled={busy} className={`${primaryButton} w-full`}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
```

`web/src/layout/Layout.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router";
import { api } from "../api/client";
import { useCurrentUser } from "../auth/RequireAuth";
import { ROLE_LABEL } from "../auth/roles";
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
  );
}
```

`web/src/home/HomePage.tsx` (Task 10 replaces it):

```tsx
import { Link } from "react-router";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";

export default function HomePage() {
  const me = useCurrentUser();
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Welcome, {me.name}</h1>
      {isHospital(me.role) && (
        <Link to="/capture" className="block rounded-xl bg-blue-700 p-6 text-center text-xl font-semibold text-white hover:bg-blue-800">
          New capture
        </Link>
      )}
    </div>
  );
}
```

`web/src/App.tsx` (replace the whole file):

```tsx
import { Route, Routes } from "react-router";
import LoginPage from "./auth/LoginPage";
import { RequireAuth } from "./auth/RequireAuth";
import HomePage from "./home/HomePage";
import { Layout } from "./layout/Layout";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <Layout>
              <AuthedRoutes />
            </Layout>
          </RequireAuth>
        }
      />
    </Routes>
  );
}

function AuthedRoutes() {
  return (
    <Routes>
      <Route index element={<HomePage />} />
      <Route path="*" element={<p>Page not found.</p>} />
    </Routes>
  );
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npm test && npm run typecheck && npm run e2e`
Expected: unit tests pass, `tsc` is clean, and Playwright reports `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "feat(web): API client, login, role-aware layout, Playwright harness" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Device setup — create or enter the hospital key

**Files:**
- Create: `web/src/storage/idb.ts`, `web/src/crypto/keyStore.ts`, `web/src/crypto/keySetup.ts`, `web/src/device/DeviceSetupPage.tsx`
- Modify: `web/src/App.tsx` (add route), `web/e2e/flow.spec.ts` (append test)
- Test: `web/src/crypto/keySetup.test.ts`

**Interfaces:**
- Consumes: `canonicalKeyString`, `fingerprintOf`, `importHmacKey`, `generateKeyString`, `formatKeyForPrint` (Task 1); `api`, `json`, `useExpectedFingerprint`, `useCurrentUser` (Task 2).
- Produces:
  - `storage/idb.ts`: `getDb()` (the `amcgh-capture` database, version 1, with stores `device` and `outbox` keyed by `id`), `resetDbForTests()`, and the types `StoredDeviceKey { cryptoKey, fingerprint }`, `OutboxMeta { study_code, template_key, key_fingerprint }`, `OutboxItem { id, createdAt, meta, pages: ArrayBuffer[], attempts, error: string|null, failed: boolean }`.
  - `keyStore.ts`: `loadDeviceKey()`, `saveDeviceKey(v)`, `clearDeviceKey()`, `useDeviceKey()` (query key `["deviceKey"]`).
  - `keySetup.ts`: `checkEnteredKey(input, expected) -> {ok:true, canonical, fingerprint} | {ok:false, message}`.
  - Route `/setup`.

- [ ] **Step 1: Write the failing tests**

`web/src/crypto/keySetup.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { checkEnteredKey } from "./keySetup";

const KEY = "000G40R40M30E209185GR38E1W8124GK2GAHC5RR34D1P70X3RFG";

describe("checkEnteredKey", () => {
  it("accepts the printed format when it matches the hospital key", async () => {
    const typed = "000g-40r4-0m30-e209-185g-r38e-1w81-24gk-2gah-c5rr-34d1-p70x-3rfg";
    expect(await checkEnteredKey(typed, "K-B9FF")).toEqual({ ok: true, canonical: KEY, fingerprint: "K-B9FF" });
  });
  it("explains a mismatch and shows the expected fingerprint", async () => {
    expect(await checkEnteredKey(KEY, "K-0000")).toEqual({
      ok: false,
      message: "This key doesn't match the hospital key (K-0000). Check for typos.",
    });
  });
  it("explains a malformed key", async () => {
    expect(await checkEnteredKey("1234", null)).toEqual({ ok: false, message: "The key must be 52 characters (ignoring dashes)" });
  });
  it("accepts any well-formed key before a hospital key exists", async () => {
    expect((await checkEnteredKey(KEY, null)).ok).toBe(true);
  });
});
```

Append to `web/e2e/flow.spec.ts`:

```ts
test("a hospital doctor sets up this browser with a new hospital key", async () => {
  await login("doctor@amcgh.test");
  await page.getByRole("link", { name: "Device setup" }).click();
  await expect(page.getByTestId("device-fingerprint")).toHaveText("no key");
  await page.getByRole("button", { name: "Generate key" }).click();
  const key = (await page.getByTestId("generated-key").textContent()) ?? "";
  expect(key).toMatch(/^([0-9A-Z]{4}-){12}[0-9A-Z]{4}$/);
  await page.getByLabel("I have written down this key and stored it safely").check();
  await page.getByRole("button", { name: "Use this key on this device" }).click();
  await expect(page.getByRole("status")).toContainText("Device ready");
  await expect(page.getByTestId("device-fingerprint")).toHaveText(/^K-[0-9A-F]{4}$/);
  await expect(page.getByText("Enter the hospital key")).toBeVisible();
  await logout();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL with `Failed to resolve import "./keySetup"`.

- [ ] **Step 3: Implement storage, key store and key check**

`web/src/storage/idb.ts`:

```ts
import { openDB, type DBSchema, type IDBPDatabase } from "idb";

export interface StoredDeviceKey {
  cryptoKey: CryptoKey;
  fingerprint: string;
}

export interface OutboxMeta {
  study_code: string;
  template_key: string;
  key_fingerprint: string;
}

/** A redacted upload waiting to be sent. Never holds unredacted images. */
export interface OutboxItem {
  id: string;
  createdAt: number;
  meta: OutboxMeta;
  pages: ArrayBuffer[];
  attempts: number;
  error: string | null;
  failed: boolean;
}

interface CaptureDb extends DBSchema {
  device: { key: string; value: StoredDeviceKey };
  outbox: { key: string; value: OutboxItem };
}

let dbPromise: Promise<IDBPDatabase<CaptureDb>> | null = null;

export function getDb(): Promise<IDBPDatabase<CaptureDb>> {
  dbPromise ??= openDB<CaptureDb>("amcgh-capture", 1, {
    upgrade(db) {
      db.createObjectStore("device");
      db.createObjectStore("outbox", { keyPath: "id" });
    },
  });
  return dbPromise;
}

export function resetDbForTests(): void {
  dbPromise = null;
}
```

`web/src/crypto/keyStore.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { getDb, type StoredDeviceKey } from "../storage/idb";

export async function loadDeviceKey(): Promise<StoredDeviceKey | null> {
  return (await (await getDb()).get("device", "key")) ?? null;
}

export async function saveDeviceKey(value: StoredDeviceKey): Promise<void> {
  await (await getDb()).put("device", value, "key");
}

export async function clearDeviceKey(): Promise<void> {
  await (await getDb()).delete("device", "key");
}

export function useDeviceKey() {
  return useQuery({ queryKey: ["deviceKey"], queryFn: loadDeviceKey, staleTime: Infinity });
}
```

`web/src/crypto/keySetup.ts`:

```ts
import { canonicalKeyString, fingerprintOf } from "./deviceKey";

export type KeyCheck = { ok: true; canonical: string; fingerprint: string } | { ok: false; message: string };

export async function checkEnteredKey(input: string, expected: string | null): Promise<KeyCheck> {
  let canonical: string;
  try {
    canonical = canonicalKeyString(input);
  } catch (e) {
    return { ok: false, message: (e as Error).message };
  }
  const fingerprint = await fingerprintOf(canonical);
  if (expected !== null && fingerprint !== expected) {
    return { ok: false, message: `This key doesn't match the hospital key (${expected}). Check for typos.` };
  }
  return { ok: true, canonical, fingerprint };
}
```

- [ ] **Step 4: Implement the page and route**

`web/src/device/DeviceSetupPage.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, json } from "../api/client";
import { useExpectedFingerprint } from "../api/hooks";
import { useCurrentUser } from "../auth/RequireAuth";
import { fingerprintOf, formatKeyForPrint, generateKeyString, importHmacKey } from "../crypto/deviceKey";
import { checkEnteredKey } from "../crypto/keySetup";
import { saveDeviceKey, useDeviceKey } from "../crypto/keyStore";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";

export default function DeviceSetupPage() {
  const me = useCurrentUser();
  const queryClient = useQueryClient();
  const expectedQuery = useExpectedFingerprint(me.role === "hospital_doctor");
  const deviceKey = useDeviceKey();
  const [generated, setGenerated] = useState<string | null>(null);
  const [writtenDown, setWrittenDown] = useState(false);
  const [entered, setEntered] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me.role !== "hospital_doctor") return <p>Only a hospital doctor can set up this device.</p>;
  if (expectedQuery.isPending || deviceKey.isPending) return <p>Loading…</p>;
  if (expectedQuery.isError) return <p role="alert" className="text-red-700">{expectedQuery.error.message}</p>;
  const expected = expectedQuery.data.expected;

  async function install(canonical: string, fingerprint: string) {
    setBusy(true);
    setMessage(null);
    try {
      await api("/device/fingerprint", { method: "POST", body: json({ fingerprint }) });
      await saveDeviceKey({ cryptoKey: await importHmacKey(canonical), fingerprint });
      setGenerated(null);
      setEntered("");
      await queryClient.invalidateQueries({ queryKey: ["deviceKey"] });
      await queryClient.invalidateQueries({ queryKey: ["fingerprint"] });
      setMessage(`Device ready — key ${fingerprint}`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Setup failed");
    } finally {
      setBusy(false);
    }
  }

  async function applyGenerated() {
    if (generated) await install(generated, await fingerprintOf(generated));
  }

  async function applyEntered() {
    const result = await checkEnteredKey(entered, expected);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    await install(result.canonical, result.fingerprint);
  }

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold">Device setup</h1>
      <p>
        This device: <strong data-testid="device-fingerprint">{deviceKey.data ? deviceKey.data.fingerprint : "no key"}</strong>
      </p>
      <p>
        Hospital key registered on the server: <strong>{expected ?? "none yet"}</strong>
      </p>
      {expected === null ? (
        <div className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">First device: create the hospital key</h2>
          <p className="text-sm text-slate-700">
            The key never leaves the hospital. Print or write it down, seal it, and give it to the two key custodians.
            Every other device needs this key.
          </p>
          {generated === null ? (
            <button type="button" onClick={() => setGenerated(generateKeyString())} className={primaryButton}>
              Generate key
            </button>
          ) : (
            <>
              <pre data-testid="generated-key" className="break-all rounded bg-slate-100 p-3 font-mono text-lg">
                {formatKeyForPrint(generated)}
              </pre>
              <label className="flex items-start gap-2">
                <input type="checkbox" checked={writtenDown} onChange={(e) => setWrittenDown(e.target.checked)} className="mt-1" />
                <span>I have written down this key and stored it safely</span>
              </label>
              <button type="button" disabled={!writtenDown || busy} onClick={applyGenerated} className={primaryButton}>
                Use this key on this device
              </button>
            </>
          )}
        </div>
      ) : (
        <div className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Enter the hospital key</h2>
          <label className="block">
            <span className="text-sm font-medium">Hospital key</span>
            <input value={entered} onChange={(e) => setEntered(e.target.value)} placeholder="XXXX-XXXX-…" autoComplete="off" spellCheck={false} className={`${inputClass} font-mono`} />
          </label>
          <button type="button" disabled={busy || !entered.trim()} onClick={applyEntered} className={secondaryButton}>
            Save key on this device
          </button>
        </div>
      )}
      {message && (
        <p role="status" className="rounded-md bg-slate-100 p-3">
          {message}
        </p>
      )}
    </section>
  );
}
```

In `web/src/App.tsx`, add the import

```tsx
import DeviceSetupPage from "./device/DeviceSetupPage";
```

and, inside `AuthedRoutes`, add this line directly above `<Route path="*" …>`:

```tsx
      <Route path="setup" element={<DeviceSetupPage />} />
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npm test && npm run typecheck && npm run e2e`
Expected: everything passes; Playwright reports `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add web/src web/e2e
git commit -m "feat(web): device setup — generate or enter the hospital key" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Image helpers and automatic name detection

**Files:**
- Create: `web/src/imaging/geometry.ts`, `web/src/imaging/blur.ts`, `web/src/imaging/render.ts`, `web/src/redaction/labels.ts`, `web/src/redaction/ocr.ts`
- Test: `web/src/imaging/imaging.test.ts`, `web/src/redaction/labels.test.ts`

**Interfaces:**
- Produces:
  - `geometry.ts`: `Rect {x,y,w,h}`, `Rotation = 0|90|180|270`, `fitWithin(w,h,maxSide) -> {width,height,scale}`, `rotatedSize(w,h,r)`, `clampRect(r,width,height)`, `scaleRect(r,s)`.
  - `blur.ts`: `BLUR_THRESHOLD = 100`, `toGray(rgba,w,h)`, `laplacianVariance(gray,w,h)`, `isBlurry(score)`.
  - `render.ts` (browser only; covered by e2e): `MAX_SIDE = 3000`, `PreparedPage {blob,width,height,blur}`, `rotateToCanvas(bitmap, rotation, maxSide)`, `preparePage(bitmap, rotation, crop|null): Promise<PreparedPage>`, `burnRedactions(page: Blob, boxes: Rect[]): Promise<Blob>` (JPEG quality 0.85).
  - `labels.ts`: `REDACTION_LABELS`, `OcrLine {text, bbox:{x0,y0,x1,y1}}`, `lineNeedsRedaction(text)`, `suggestBoxes(lines, pad = 6) -> Rect[]`.
  - `ocr.ts` (browser only): `ocrLines(image: Blob): Promise<OcrLine[]>`, using the self-hosted assets under `/tesseract/`.

- [ ] **Step 1: Write the failing tests**

`web/src/imaging/imaging.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { BLUR_THRESHOLD, isBlurry, laplacianVariance, toGray } from "./blur";
import { clampRect, fitWithin, rotatedSize, scaleRect } from "./geometry";

function image(width: number, height: number, f: (x: number, y: number) => number): Float32Array {
  const gray = new Float32Array(width * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) gray[y * width + x] = f(x, y);
  return gray;
}

describe("geometry", () => {
  it("shrinks large images to the size limit", () => {
    expect(fitWithin(6000, 4000, 3000)).toEqual({ width: 3000, height: 2000, scale: 0.5 });
  });
  it("never enlarges small images", () => {
    expect(fitWithin(800, 600, 3000)).toEqual({ width: 800, height: 600, scale: 1 });
  });
  it("swaps sides for quarter turns", () => {
    expect(rotatedSize(400, 300, 90)).toEqual({ width: 300, height: 400 });
    expect(rotatedSize(400, 300, 180)).toEqual({ width: 400, height: 300 });
  });
  it("keeps a crop rectangle inside the image", () => {
    expect(clampRect({ x: -10, y: 50, w: 500, h: 500 }, 400, 300)).toEqual({ x: 0, y: 50, w: 400, h: 250 });
  });
  it("scales rectangles", () => {
    expect(scaleRect({ x: 10, y: 20, w: 30, h: 40 }, 2)).toEqual({ x: 20, y: 40, w: 60, h: 80 });
  });
});

describe("blur detection", () => {
  it("finds no detail in a flat image", () => {
    expect(laplacianVariance(image(20, 20, () => 128), 20, 20)).toBe(0);
  });
  it("treats a smooth gradient as blurry", () => {
    expect(isBlurry(laplacianVariance(image(50, 50, (x) => x * 2), 50, 50))).toBe(true);
  });
  it("treats sharp black-and-white detail as sharp", () => {
    const score = laplacianVariance(image(50, 50, (x, y) => ((x + y) % 2 ? 255 : 0)), 50, 50);
    expect(score).toBeGreaterThan(BLUR_THRESHOLD);
    expect(isBlurry(score)).toBe(false);
  });
  it("treats tiny images as blurry", () => {
    expect(laplacianVariance(new Float32Array(4), 2, 2)).toBe(0);
  });
  it("converts RGBA to luma", () => {
    const gray = toGray(new Uint8ClampedArray([255, 0, 0, 255, 0, 0, 255, 255]), 2, 1);
    expect(gray[0]).toBeCloseTo(76.245);
    expect(gray[1]).toBeCloseTo(29.07);
  });
});
```

`web/src/redaction/labels.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { lineNeedsRedaction, suggestBoxes } from "./labels";

describe("lineNeedsRedaction", () => {
  it.each([
    "Patient Name: Rahim Uddin",
    "Name : Test Person",
    "Pt. Name: X",
    "Mobile: 01712345678",
    "Contact 017-1234-5678",
    "Call +8801812345678 for results",
    "S/O: Abdul Karim",
    "Reg No: AMH-00123",
    "Date: 01/09/2026   Patient Name: Test Person",
    "UHID 99881",
    "Father's name Karim",
    "Address: House 5, Road 2, Uttara",
  ])("hides %s", (line) => {
    expect(lineNeedsRedaction(line)).toBe(true);
  });

  it.each([
    "Findings: 2.3 x 1.8 cm spiculated mass in right upper lobe.",
    "Impression: Suspicious for primary lung malignancy.",
    "Date: 01/09/2026",
    "Identification of a new nodule",
    "Region of interest drawn on axial image 42",
    "CT CHEST WITH CONTRAST",
  ])("keeps %s", (line) => {
    expect(lineNeedsRedaction(line)).toBe(false);
  });
});

describe("suggestBoxes", () => {
  it("pads each matching line and clamps at the image edge", () => {
    const boxes = suggestBoxes([
      { text: "Patient Name: Test", bbox: { x0: 2, y0: 20, x1: 110, y1: 40 } },
      { text: "Findings: mass", bbox: { x0: 10, y0: 60, x1: 200, y1: 80 } },
    ]);
    // x0=2 minus padding is clamped to 0, so the width is measured from the clamped edge: 110 + 6 - 0.
    expect(boxes).toEqual([{ x: 0, y: 14, w: 116, h: 32 }]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL with `Failed to resolve import "./blur"` and `"./labels"`.

- [ ] **Step 3: Implement geometry and blur**

`web/src/imaging/geometry.ts`:

```ts
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type Rotation = 0 | 90 | 180 | 270;

export function fitWithin(width: number, height: number, maxSide: number) {
  const scale = Math.min(1, maxSide / Math.max(width, height));
  return { width: Math.round(width * scale), height: Math.round(height * scale), scale };
}

export function rotatedSize(width: number, height: number, rotation: Rotation) {
  return rotation === 90 || rotation === 270 ? { width: height, height: width } : { width, height };
}

export function clampRect(r: Rect, width: number, height: number): Rect {
  const x = Math.max(0, Math.min(r.x, width));
  const y = Math.max(0, Math.min(r.y, height));
  return { x, y, w: Math.max(1, Math.min(r.w, width - x)), h: Math.max(1, Math.min(r.h, height - y)) };
}

export function scaleRect(r: Rect, s: number): Rect {
  return { x: r.x * s, y: r.y * s, w: r.w * s, h: r.h * s };
}
```

`web/src/imaging/blur.ts`:

```ts
/** Below this Laplacian variance a photo is probably too blurry to read. Tune during the pilot. */
export const BLUR_THRESHOLD = 100;

export function toGray(rgba: Uint8ClampedArray, width: number, height: number): Float32Array {
  const gray = new Float32Array(width * height);
  for (let i = 0; i < width * height; i++) {
    gray[i] = 0.299 * rgba[i * 4] + 0.587 * rgba[i * 4 + 1] + 0.114 * rgba[i * 4 + 2];
  }
  return gray;
}

/** Variance of the 4-neighbour Laplacian: high for sharp edges, low for blur. */
export function laplacianVariance(gray: Float32Array, width: number, height: number): number {
  if (width < 3 || height < 3) return 0;
  let sum = 0;
  let sumSq = 0;
  let n = 0;
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const lap = gray[i - width] + gray[i + width] + gray[i - 1] + gray[i + 1] - 4 * gray[i];
      sum += lap;
      sumSq += lap * lap;
      n++;
    }
  }
  const mean = sum / n;
  return sumSq / n - mean * mean;
}

export function isBlurry(score: number): boolean {
  return score < BLUR_THRESHOLD;
}
```

- [ ] **Step 4: Implement the canvas helpers**

`web/src/imaging/render.ts`:

```ts
import { laplacianVariance, toGray } from "./blur";
import { fitWithin, rotatedSize, type Rect, type Rotation } from "./geometry";

export const MAX_SIDE = 3000;

export interface PreparedPage {
  blob: Blob;
  width: number;
  height: number;
  blur: number;
}

function canvas(width: number, height: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  return c;
}

export function rotateToCanvas(bitmap: ImageBitmap, rotation: Rotation, maxSide: number): HTMLCanvasElement {
  const turned = rotatedSize(bitmap.width, bitmap.height, rotation);
  const { width, height, scale } = fitWithin(turned.width, turned.height, maxSide);
  const out = canvas(width, height);
  const ctx = out.getContext("2d")!;
  ctx.translate(width / 2, height / 2);
  ctx.rotate((rotation * Math.PI) / 180);
  ctx.scale(scale, scale);
  ctx.drawImage(bitmap, -bitmap.width / 2, -bitmap.height / 2);
  return out;
}

function toJpeg(source: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) =>
    source.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not encode the image"))), "image/jpeg", quality),
  );
}

function blurScore(source: HTMLCanvasElement): number {
  const { width, height } = fitWithin(source.width, source.height, 512);
  const small = canvas(width, height);
  const ctx = small.getContext("2d")!;
  ctx.drawImage(source, 0, 0, width, height);
  return laplacianVariance(toGray(ctx.getImageData(0, 0, width, height).data, width, height), width, height);
}

/** Rotate and crop at full resolution, shrink to MAX_SIDE, and encode a high-quality working copy. */
export async function preparePage(bitmap: ImageBitmap, rotation: Rotation, crop: Rect | null): Promise<PreparedPage> {
  const rotated = rotateToCanvas(bitmap, rotation, Number.MAX_SAFE_INTEGER);
  const area = crop ?? { x: 0, y: 0, w: rotated.width, h: rotated.height };
  const { width, height } = fitWithin(area.w, area.h, MAX_SIDE);
  const out = canvas(width, height);
  out.getContext("2d")!.drawImage(rotated, area.x, area.y, area.w, area.h, 0, 0, width, height);
  return { blob: await toJpeg(out, 0.92), width, height, blur: blurScore(out) };
}

/** Burn solid black boxes into the page and re-encode it; the re-encode also drops EXIF/GPS metadata. */
export async function burnRedactions(page: Blob, boxes: Rect[]): Promise<Blob> {
  const bitmap = await createImageBitmap(page);
  const out = canvas(bitmap.width, bitmap.height);
  const ctx = out.getContext("2d")!;
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  ctx.fillStyle = "#000";
  for (const box of boxes) ctx.fillRect(box.x, box.y, box.w, box.h);
  return toJpeg(out, 0.85);
}
```

- [ ] **Step 5: Implement label matching and the OCR wrapper**

`web/src/redaction/labels.ts`:

```ts
import type { Rect } from "../imaging/geometry";

/** Line labels that introduce patient identifiers (spec §4.3). */
export const REDACTION_LABELS = [
  "Name", "Patient", "Pt", "Mobile", "Mob", "Phone", "Cell", "Contact", "Address", "Addr",
  "Father", "Husband", "Guardian", "S/O", "D/O", "W/O", "Reg", "Registration", "ID", "MRN", "UHID", "NID",
];

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const ALTERNATION = REDACTION_LABELS.map(escape).join("|");
const STARTS_WITH_LABEL = new RegExp(`^\\s*(?:${ALTERNATION})(?![A-Za-z])`, "i");
const LABEL_THEN_COLON = new RegExp(`\\b(?:${ALTERNATION})\\b\\.?\\s*(?:No\\.?|Number)?\\s*:`, "i");
const BD_MOBILE = /(?:\+?88)?01[3-9]\d{8}/;

export interface OcrLine {
  text: string;
  bbox: { x0: number; y0: number; x1: number; y1: number };
}

export function lineNeedsRedaction(text: string): boolean {
  if (BD_MOBILE.test(text.replace(/[\s-]/g, ""))) return true;
  return STARTS_WITH_LABEL.test(text) || LABEL_THEN_COLON.test(text);
}

export function suggestBoxes(lines: OcrLine[], pad = 6): Rect[] {
  return lines
    .filter((line) => lineNeedsRedaction(line.text))
    .map(({ bbox }) => {
      const x = Math.max(0, bbox.x0 - pad);
      const y = Math.max(0, bbox.y0 - pad);
      return { x, y, w: bbox.x1 + pad - x, h: bbox.y1 + pad - y };
    });
}
```

`web/src/redaction/ocr.ts`:

```ts
import { createWorker, type Worker } from "tesseract.js";
import type { OcrLine } from "./labels";

let workerPromise: Promise<Worker> | null = null;

function getWorker(): Promise<Worker> {
  workerPromise ??= createWorker("eng", undefined, {
    workerPath: "/tesseract/worker.min.js",
    corePath: "/tesseract/core",
    langPath: "/tesseract/lang",
    workerBlobURL: false,
  });
  return workerPromise;
}

/** Text lines with pixel boxes, recognised entirely on this device. */
export async function ocrLines(image: Blob): Promise<OcrLine[]> {
  const worker = await getWorker();
  const { data } = await worker.recognize(image, {}, { blocks: true });
  return (data.blocks ?? []).flatMap((block) =>
    block.paragraphs.flatMap((paragraph) => paragraph.lines.map((line) => ({ text: line.text, bbox: line.bbox }))),
  );
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd web && npm test && npm run typecheck`
Expected: all pass, `tsc` clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/imaging web/src/redaction
git commit -m "feat(web): blur check, crop/rotate/redact canvas helpers, on-device name detection" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Outbox — redacted uploads that survive a bad connection

**Files:**
- Create: `web/src/outbox/outbox.ts`, `web/src/outbox/OutboxContext.tsx`
- Modify: `web/src/layout/Layout.tsx` (wrap in the provider and show a waiting count)
- Test: `web/src/outbox/outbox.test.ts`

**Interfaces:**
- Consumes: `getDb`, `OutboxItem`, `OutboxMeta`, `resetDbForTests` (Task 3); `errorMessage` (Task 2).
- Produces:
  - `SendOutcome = "done"|"retry"|"fail"`, `SendResult {outcome, recordId?, duplicateOf?, error?}`.
  - `classifyStatus(status)`.
  - `enqueue(meta, pages: Blob[]) -> OutboxItem`.
  - `listOutbox()`.
  - `discard(id)`.
  - `sendItem(item, fetchImpl?)`.
  - `flushOutbox(fetchImpl?) -> Map<itemId, SendResult>`. Overlapping calls share one run; failed items are skipped.
  - `OutboxProvider` and `useOutbox() -> {items, refresh, flush, discard}`. The provider flushes on mount, every 30 s, and on the browser `online` event.

- [ ] **Step 1: Write the failing tests**

`web/src/outbox/outbox.test.ts`:

```ts
import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetDbForTests } from "../storage/idb";
import { classifyStatus, discard, enqueue, flushOutbox, listOutbox } from "./outbox";

const META = { study_code: "AMH-N0ZDG4KM8V", template_key: "radiology_report", key_fingerprint: "K-B9FF" };
const jpeg = () => new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], { type: "image/jpeg" });
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const asFetch = (f: (...args: never[]) => Promise<Response>) => f as unknown as typeof fetch;

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetDbForTests();
});

describe("classifyStatus", () => {
  it.each([
    [201, "done"],
    [401, "retry"],
    [408, "retry"],
    [429, "retry"],
    [503, "retry"],
    [409, "fail"],
    [413, "fail"],
    [415, "fail"],
    [422, "fail"],
  ] as const)("%i -> %s", (status, outcome) => {
    expect(classifyStatus(status)).toBe(outcome);
  });
});

describe("outbox", () => {
  it("stores redacted pages as bytes", async () => {
    await enqueue(META, [jpeg(), jpeg()]);
    const [item] = await listOutbox();
    expect(item.meta).toEqual(META);
    expect(item.pages.map((p) => p.byteLength)).toEqual([4, 4]);
    expect(item).toMatchObject({ attempts: 0, error: null, failed: false });
  });

  it("sends meta and pages, then removes the item", async () => {
    const item = await enqueue(META, [jpeg(), jpeg()]);
    const fetchMock = vi.fn(async () => reply(201, { id: "rec-1", duplicate_of: [] }));
    const results = await flushOutbox(asFetch(fetchMock));
    expect(results.get(item.id)).toEqual({ outcome: "done", recordId: "rec-1", duplicateOf: [] });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/records");
    const form = init.body as FormData;
    expect(JSON.parse(form.get("meta") as string)).toEqual(META);
    expect(form.getAll("pages")).toHaveLength(2);
    expect(await listOutbox()).toEqual([]);
  });

  it("keeps the item after a server error and sends it later", async () => {
    const item = await enqueue(META, [jpeg()]);
    await flushOutbox(asFetch(async () => reply(503, { detail: "Service unavailable" })));
    expect((await listOutbox())[0]).toMatchObject({ id: item.id, attempts: 1, failed: false, error: "Service unavailable" });
    await flushOutbox(asFetch(async () => reply(201, { id: "rec-2", duplicate_of: [] })));
    expect(await listOutbox()).toEqual([]);
  });

  it("keeps the item when the session expired", async () => {
    await enqueue(META, [jpeg()]);
    await flushOutbox(asFetch(async () => reply(401, { detail: "Not logged in" })));
    expect((await listOutbox())[0]).toMatchObject({ failed: false, attempts: 1 });
  });

  it("keeps the item when offline", async () => {
    await enqueue(META, [jpeg()]);
    const results = await flushOutbox(
      asFetch(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    expect([...results.values()][0]).toEqual({ outcome: "retry", error: "No connection — will retry" });
    expect(await listOutbox()).toHaveLength(1);
  });

  it("sets a refused upload aside with the server's reason and stops retrying it", async () => {
    await enqueue(META, [jpeg()]);
    await flushOutbox(asFetch(async () => reply(409, { detail: "This device's key doesn't match — ask your hospital admin." })));
    const [item] = await listOutbox();
    expect(item.failed).toBe(true);
    expect(item.error).toBe("This device's key doesn't match — ask your hospital admin.");
    const fetchMock = vi.fn();
    await flushOutbox(asFetch(fetchMock));
    expect(fetchMock).not.toHaveBeenCalled();
    await discard(item.id);
    expect(await listOutbox()).toEqual([]);
  });

  it("never sends an item twice when flushes overlap", async () => {
    await enqueue(META, [jpeg()]);
    const fetchMock = vi.fn(async () => reply(201, { id: "rec-3", duplicate_of: [] }));
    await Promise.all([flushOutbox(asFetch(fetchMock)), flushOutbox(asFetch(fetchMock))]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL with `Failed to resolve import "./outbox"`.

- [ ] **Step 3: Implement the outbox**

`web/src/outbox/outbox.ts`:

```ts
import { errorMessage } from "../api/client";
import { getDb, type OutboxItem, type OutboxMeta } from "../storage/idb";

export type SendOutcome = "done" | "retry" | "fail";

export interface SendResult {
  outcome: SendOutcome;
  recordId?: string;
  duplicateOf?: string[];
  error?: string;
}

export function classifyStatus(status: number): SendOutcome {
  if (status >= 200 && status < 300) return "done";
  if (status === 401 || status === 408 || status === 429 || status >= 500) return "retry";
  return "fail";
}

export async function enqueue(meta: OutboxMeta, pages: Blob[]): Promise<OutboxItem> {
  const item: OutboxItem = {
    id: crypto.randomUUID(),
    createdAt: Date.now(),
    meta,
    pages: await Promise.all(pages.map((page) => page.arrayBuffer())),
    attempts: 0,
    error: null,
    failed: false,
  };
  await (await getDb()).put("outbox", item);
  return item;
}

export async function listOutbox(): Promise<OutboxItem[]> {
  return (await (await getDb()).getAll("outbox")).sort((a, b) => a.createdAt - b.createdAt);
}

export async function discard(id: string): Promise<void> {
  await (await getDb()).delete("outbox", id);
}

export async function sendItem(item: OutboxItem, fetchImpl: typeof fetch = fetch): Promise<SendResult> {
  const form = new FormData();
  form.append("meta", JSON.stringify(item.meta));
  item.pages.forEach((bytes, i) => form.append("pages", new Blob([bytes], { type: "image/jpeg" }), `page-${i + 1}.jpg`));
  let res: Response;
  try {
    res = await fetchImpl("/api/records", { method: "POST", body: form, credentials: "same-origin" });
  } catch {
    return { outcome: "retry", error: "No connection — will retry" };
  }
  const body: unknown = await res.json().catch(() => null);
  const outcome = classifyStatus(res.status);
  if (outcome === "done") {
    const record = body as { id: string; duplicate_of: string[] };
    return { outcome, recordId: record.id, duplicateOf: record.duplicate_of };
  }
  return { outcome, error: errorMessage(res.status, body) };
}

async function runFlush(fetchImpl: typeof fetch): Promise<Map<string, SendResult>> {
  const results = new Map<string, SendResult>();
  const db = await getDb();
  for (const item of await listOutbox()) {
    if (item.failed) continue;
    const result = await sendItem(item, fetchImpl);
    results.set(item.id, result);
    if (result.outcome === "done") {
      await db.delete("outbox", item.id);
    } else {
      await db.put("outbox", { ...item, attempts: item.attempts + 1, error: result.error ?? null, failed: result.outcome === "fail" });
    }
  }
  return results;
}

let inFlight: Promise<Map<string, SendResult>> | null = null;

/** Send every waiting item once. Overlapping calls share the same run so nothing is sent twice. */
export function flushOutbox(fetchImpl: typeof fetch = fetch): Promise<Map<string, SendResult>> {
  inFlight ??= runFlush(fetchImpl).finally(() => {
    inFlight = null;
  });
  return inFlight;
}
```

- [ ] **Step 4: Implement the provider and show it in the layout**

`web/src/outbox/OutboxContext.tsx`:

```tsx
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { OutboxItem } from "../storage/idb";
import { discard as discardItem, flushOutbox, listOutbox } from "./outbox";

export interface OutboxState {
  items: OutboxItem[];
  refresh: () => Promise<void>;
  flush: () => Promise<void>;
  discard: (id: string) => Promise<void>;
}

const OutboxContext = createContext<OutboxState | null>(null);

export function OutboxProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<OutboxItem[]>([]);
  const refresh = useCallback(async () => setItems(await listOutbox()), []);
  const flush = useCallback(async () => {
    await flushOutbox();
    await refresh();
  }, [refresh]);
  const discard = useCallback(
    async (id: string) => {
      await discardItem(id);
      await refresh();
    },
    [refresh],
  );

  useEffect(() => {
    void flush();
    const timer = window.setInterval(() => void flush(), 30_000);
    const onOnline = () => void flush();
    window.addEventListener("online", onOnline);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", onOnline);
    };
  }, [flush]);

  return <OutboxContext.Provider value={{ items, refresh, flush, discard }}>{children}</OutboxContext.Provider>;
}

export function useOutbox(): OutboxState {
  const value = useContext(OutboxContext);
  if (!value) throw new Error("useOutbox must be used inside OutboxProvider");
  return value;
}
```

In `web/src/layout/Layout.tsx`:

1. Add the import `import { OutboxProvider, useOutbox } from "../outbox/OutboxContext";`.
2. Add this component at the end of the file:

```tsx
function OutboxCount() {
  const { items } = useOutbox();
  const waiting = items.filter((item) => !item.failed).length;
  return waiting > 0 ? <span className="text-sm font-medium text-amber-700">{waiting} waiting to upload</span> : null;
}
```

3. Change the component's returned JSX to wrap everything in the provider and show the count before the user's name:

```tsx
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npm test && npm run typecheck && npm run e2e`
Expected: all pass. The e2e run checks that the layout still renders with the provider.

- [ ] **Step 6: Commit**

```bash
git add web/src/outbox web/src/layout
git commit -m "feat(web): IndexedDB outbox for redacted uploads with safe retries" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Capture wizard — patient, form type, photos and crop

**Files:**
- Create: `web/src/capture/types.ts`, `web/src/capture/CapturePage.tsx`, `web/src/capture/PatientStep.tsx`, `web/src/capture/TemplateStep.tsx`, `web/src/capture/PhotosStep.tsx`, `web/src/capture/CropEditor.tsx`, `web/e2e/fixtures/make_report.py`, `web/e2e/fixtures/report.jpg` (generated)
- Modify: `web/src/App.tsx` (add route), `web/e2e/flow.spec.ts` (append test)

**Interfaces:**
- Consumes: `studyCodeFor` (Task 1); `useDeviceKey` (Task 3); `useTemplates`, `useCurrentUser`, `isHospital` (Task 2); `preparePage`, `rotateToCanvas`, `PreparedPage`, `isBlurry`, geometry helpers (Task 4).
- Produces:
  - `PageDraft {id, blob, url, width, height, blur, boxes: Rect[], ocrDone}` (unredacted, memory only).
  - `CapturePage` with steps `patient → template → photos → redact`. The redact step is wired in Task 7.
  - Route `/capture`.
  - Accessible names used by e2e:
    - Patient step: label `Hospital registration number`, button `Get study code`, test id `study-code`, buttons `Continue` and `Different patient`.
    - Form step: one button per template title, locked ones disabled.
    - Photos step: inputs with test ids `camera-input` and `gallery-input`, buttons `Take photo`, `Choose from gallery`, `Next: hide names`, images with alt text `Page N`.
    - Crop editor: buttons `Rotate left`, `Rotate right`, `Reset crop`, `Cancel`, `Use this page`.

- [ ] **Step 1: Generate the synthetic report photo**

`web/e2e/fixtures/make_report.py`:

```python
"""Writes report.jpg: a made-up radiology report for end-to-end tests (no real patient)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LINES = [
    "AHSANIA MISSION CANCER & GENERAL HOSPITAL (DEMO)",
    "Patient Name: Test Person",
    "Mobile: 01712345678",
    "Reg No: AMH-00123",
    "",
    "CT CHEST REPORT",
    "Date: 01/09/2026",
    "Findings: 2.3 x 1.8 cm spiculated mass in right upper lobe.",
    "Impression: Suspicious for primary lung malignancy.",
]

image = Image.new("RGB", (1800, 1100), "white")
draw = ImageDraw.Draw(image)
font = ImageFont.load_default(size=44)
for i, line in enumerate(LINES):
    draw.text((60, 60 + 100 * i), line, fill="black", font=font)
image.save(Path(__file__).with_name("report.jpg"), quality=92)
```

Run: `cd web && uv run --no-project --with pillow python e2e/fixtures/make_report.py`
Expected: `web/e2e/fixtures/report.jpg` exists (1800 × 1100). Line *n* starts at y = 60 + 100·n: "Patient Name" at y=160, "Mobile" at 260, "Findings" at 760.

- [ ] **Step 2: Write the failing e2e test**

In `web/e2e/flow.spec.ts`, add `import { fileURLToPath } from "node:url";` to the imports at the top, then append:

```ts
const REPORT = fileURLToPath(new URL("./fixtures/report.jpg", import.meta.url));
let studyCode = "";

test("the uploader turns a registration number into a study code and adds a cropped page", async () => {
  await login("uploader@amcgh.test");
  await page.getByRole("link", { name: "New capture" }).click();
  await page.getByLabel("Hospital registration number").fill("AMH-00123");
  await page.getByRole("button", { name: "Get study code" }).click();
  studyCode = (await page.getByTestId("study-code").textContent()) ?? "";
  expect(studyCode).toMatch(/^AMH-[0-9A-HJKMNP-TV-Z]{10}$/);
  await expect(page.getByLabel("Hospital registration number")).toHaveCount(0);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("button", { name: /Pathology/ })).toBeDisabled();
  await page.getByRole("button", { name: /Radiology report/ }).click();
  await page.getByTestId("gallery-input").setInputFiles(REPORT);
  await page.getByRole("button", { name: "Rotate right" }).click();
  await page.getByRole("button", { name: "Rotate left" }).click();
  await page.getByRole("button", { name: "Use this page" }).click();
  await expect(page.getByRole("img", { name: "Page 1" })).toBeVisible();
  await expect(page.getByText("Photo looks blurry — retake?")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Next: hide names" })).toBeEnabled();
});
```

Run: `cd web && npm run e2e`
Expected: the new test FAILS because "New capture" leads to "Page not found."

- [ ] **Step 3: Implement the wizard steps**

`web/src/capture/types.ts`:

```ts
import type { Rect } from "../imaging/geometry";

/** One photographed page during capture. Unredacted: lives in memory only, never stored. */
export interface PageDraft {
  id: string;
  blob: Blob;
  url: string;
  width: number;
  height: number;
  blur: number;
  boxes: Rect[];
  ocrDone: boolean;
}
```

`web/src/capture/PatientStep.tsx`:

```tsx
import { useState, type FormEvent } from "react";
import { studyCodeFor } from "../crypto/studyCode";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";

interface Props {
  cryptoKey: CryptoKey;
  onDone: (studyCode: string) => void;
}

export function PatientStep({ cryptoKey, onDone }: Props) {
  const [regNo, setRegNo] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function compute(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      setCode(await studyCodeFor(cryptoKey, regNo));
      setRegNo(""); // the registration number never leaves this screen
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (code) {
    return (
      <div className={`${card} space-y-3`}>
        <p className="text-sm text-slate-600">Study code</p>
        <p data-testid="study-code" className="font-mono text-2xl">{code}</p>
        <p className="text-sm text-slate-600">The registration number has been cleared from this screen.</p>
        <div className="flex gap-2">
          <button type="button" onClick={() => setCode(null)} className={secondaryButton}>Different patient</button>
          <button type="button" onClick={() => onDone(code)} className={primaryButton}>Continue</button>
        </div>
      </div>
    );
  }
  return (
    <form onSubmit={compute} className={`${card} space-y-3`}>
      <label className="block">
        <span className="text-sm font-medium">Hospital registration number</span>
        <input value={regNo} onChange={(e) => setRegNo(e.target.value)} autoComplete="off" required className={inputClass} />
      </label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button type="submit" className={primaryButton}>Get study code</button>
    </form>
  );
}
```

`web/src/capture/TemplateStep.tsx`:

```tsx
import { useTemplates } from "../api/hooks";
import type { TemplateOut } from "../api/types";
import { secondaryButton } from "../ui/styles";

interface Props {
  onDone: (template: TemplateOut) => void;
  onBack: () => void;
}

export function TemplateStep({ onDone, onBack }: Props) {
  const templates = useTemplates();
  if (templates.isPending) return <p>Loading forms…</p>;
  if (templates.isError) return <p role="alert" className="text-red-700">{templates.error.message}</p>;
  const photographable = templates.data.filter((t) => t.kind !== "dicom");
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">What are you photographing?</h2>
      <div className="grid gap-2 sm:grid-cols-2">
        {photographable.map((t) => (
          <button
            key={t.key}
            type="button"
            disabled={t.locked}
            onClick={() => onDone(t)}
            className="rounded-lg border border-slate-300 bg-white p-4 text-left hover:border-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="block font-medium">{t.title}</span>
            {t.locked && <span className="text-sm text-slate-600">Locked until Phase 3</span>}
          </button>
        ))}
      </div>
      <button type="button" onClick={onBack} className={secondaryButton}>Back</button>
    </div>
  );
}
```

`web/src/capture/CropEditor.tsx`:

```tsx
import type Konva from "konva";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Image as KonvaImage, Layer, Rect as KonvaRect, Stage, Transformer } from "react-konva";
import { clampRect, rotatedSize, scaleRect, type Rect, type Rotation } from "../imaging/geometry";
import { preparePage, rotateToCanvas, type PreparedPage } from "../imaging/render";
import { primaryButton, secondaryButton } from "../ui/styles";

interface Props {
  bitmap: ImageBitmap;
  onCancel: () => void;
  onDone: (page: PreparedPage) => void;
}

export function CropEditor({ bitmap, onCancel, onDone }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<Konva.Rect>(null);
  const transformerRef = useRef<Konva.Transformer>(null);
  const [rotation, setRotation] = useState<Rotation>(0);
  const [displayWidth, setDisplayWidth] = useState(0);
  const [crop, setCrop] = useState<Rect | null>(null); // stage pixels; null = whole image
  const [busy, setBusy] = useState(false);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setDisplayWidth(Math.min(el.clientWidth, 900));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const preview = useMemo(() => rotateToCanvas(bitmap, rotation, 1200), [bitmap, rotation]);
  const stageWidth = displayWidth;
  const stageHeight = displayWidth > 0 ? Math.round((preview.height * displayWidth) / preview.width) : 0;
  const frame = crop ?? { x: 0, y: 0, w: stageWidth, h: stageHeight };

  useEffect(() => setCrop(null), [rotation, stageWidth]);
  useEffect(() => {
    if (transformerRef.current && frameRef.current) {
      transformerRef.current.nodes([frameRef.current]);
      transformerRef.current.getLayer()?.batchDraw();
    }
  }, [stageWidth, stageHeight, rotation]);

  async function done() {
    setBusy(true);
    try {
      const full = rotatedSize(bitmap.width, bitmap.height, rotation);
      const cropInFullPixels = crop === null ? null : clampRect(scaleRect(crop, full.width / stageWidth), full.width, full.height);
      onDone(await preparePage(bitmap, rotation, cropInFullPixels));
    } finally {
      setBusy(false);
    }
  }

  const turn = (delta: 90 | 270) => setRotation(((rotation + delta) % 360) as Rotation);

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">Crop and straighten</h2>
      <p className="text-sm text-slate-600">Drag the blue frame's corners so only the document is inside.</p>
      <div ref={containerRef} className="w-full">
        {stageWidth > 0 && (
          <Stage width={stageWidth} height={stageHeight}>
            <Layer>
              <KonvaImage image={preview} width={stageWidth} height={stageHeight} />
              <KonvaRect
                ref={frameRef}
                x={frame.x}
                y={frame.y}
                width={frame.w}
                height={frame.h}
                stroke="#1d4ed8"
                strokeWidth={3}
                draggable
                onDragEnd={(e) => setCrop({ ...frame, x: e.target.x(), y: e.target.y() })}
                onTransformEnd={(e) => {
                  const node = e.target;
                  const w = Math.max(20, node.width() * node.scaleX());
                  const h = Math.max(20, node.height() * node.scaleY());
                  node.scaleX(1);
                  node.scaleY(1);
                  setCrop({ x: node.x(), y: node.y(), w, h });
                }}
              />
              <Transformer ref={transformerRef} rotateEnabled={false} keepRatio={false} />
            </Layer>
          </Stage>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => turn(270)} className={secondaryButton}>Rotate left</button>
        <button type="button" onClick={() => turn(90)} className={secondaryButton}>Rotate right</button>
        <button type="button" onClick={() => setCrop(null)} className={secondaryButton}>Reset crop</button>
        <button type="button" onClick={onCancel} className={secondaryButton}>Cancel</button>
        <button type="button" disabled={busy || stageWidth === 0} onClick={done} className={primaryButton}>
          {busy ? "Preparing…" : "Use this page"}
        </button>
      </div>
    </div>
  );
}
```

`web/src/capture/PhotosStep.tsx`:

```tsx
import { useRef, useState, type ChangeEvent } from "react";
import { isBlurry } from "../imaging/blur";
import type { PreparedPage } from "../imaging/render";
import { card, primaryButton, secondaryButton } from "../ui/styles";
import { CropEditor } from "./CropEditor";
import type { PageDraft } from "./types";

interface Props {
  pages: PageDraft[];
  onChange: (pages: PageDraft[]) => void;
  onBack: () => void;
  onNext: () => void;
}

export function PhotosStep({ pages, onChange, onBack, onNext }: Props) {
  const [editing, setEditing] = useState<ImageBitmap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError(null);
    try {
      setEditing(await createImageBitmap(file, { imageOrientation: "from-image" }));
    } catch {
      setError("This file could not be opened as an image. Try taking the photo again.");
    }
  }

  function addPage(page: PreparedPage) {
    editing?.close();
    setEditing(null);
    onChange([
      ...pages,
      { id: crypto.randomUUID(), blob: page.blob, url: URL.createObjectURL(page.blob), width: page.width, height: page.height, blur: page.blur, boxes: [], ocrDone: false },
    ]);
  }

  function remove(id: string) {
    const page = pages.find((p) => p.id === id);
    if (page) URL.revokeObjectURL(page.url);
    onChange(pages.filter((p) => p.id !== id));
  }

  if (editing) {
    return (
      <CropEditor
        bitmap={editing}
        onCancel={() => {
          editing.close();
          setEditing(null);
        }}
        onDone={addPage}
      />
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Photos</h2>
      {pages.length === 0 && <p className="text-slate-600">Take a photo of each page. Fill the frame and avoid glare.</p>}
      <ol className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {pages.map((p, i) => (
          <li key={p.id} className={card}>
            <img src={p.url} alt={`Page ${i + 1}`} className="h-40 w-full object-contain" />
            {isBlurry(p.blur) && <p className="mt-1 text-sm text-amber-700">Photo looks blurry — retake?</p>}
            <button type="button" onClick={() => remove(p.id)} className={`${secondaryButton} mt-2 w-full`}>
              Remove page {i + 1}
            </button>
          </li>
        ))}
      </ol>
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" onChange={onFile} className="hidden" data-testid="camera-input" />
      <input ref={galleryRef} type="file" accept="image/*" onChange={onFile} className="hidden" data-testid="gallery-input" />
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => cameraRef.current?.click()} className={primaryButton}>
          {pages.length ? "Take another photo" : "Take photo"}
        </button>
        <button type="button" onClick={() => galleryRef.current?.click()} className={secondaryButton}>
          Choose from gallery
        </button>
      </div>
      <div className="flex gap-2">
        <button type="button" onClick={onBack} className={secondaryButton}>Back</button>
        <button type="button" disabled={pages.length === 0} onClick={onNext} className={primaryButton}>Next: hide names</button>
      </div>
    </div>
  );
}
```

`web/src/capture/CapturePage.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import type { TemplateOut } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";
import { useDeviceKey } from "../crypto/keyStore";
import { PatientStep } from "./PatientStep";
import { PhotosStep } from "./PhotosStep";
import { TemplateStep } from "./TemplateStep";
import type { PageDraft } from "./types";

type Step = "patient" | "template" | "photos" | "redact";
const STEP_LABEL: Record<Step, string> = { patient: "1. Patient", template: "2. Form", photos: "3. Photos", redact: "4. Hide names" };

export default function CapturePage() {
  const me = useCurrentUser();
  const deviceKey = useDeviceKey();
  const [step, setStep] = useState<Step>("patient");
  const [studyCode, setStudyCode] = useState<string | null>(null);
  const [template, setTemplate] = useState<TemplateOut | null>(null);
  const [pages, setPages] = useState<PageDraft[]>([]);
  const pagesRef = useRef(pages);

  useEffect(() => {
    pagesRef.current = pages;
  }, [pages]);
  useEffect(() => () => pagesRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  if (!isHospital(me.role)) return <p>Only hospital staff can capture documents.</p>;
  if (deviceKey.isPending) return <p>Loading…</p>;
  if (!deviceKey.data) {
    return (
      <p>
        This device has no hospital key.{" "}
        {me.role === "hospital_doctor" ? <Link to="/setup" className="underline">Set it up</Link> : "Ask a hospital doctor to set it up."}
      </p>
    );
  }
  const key = deviceKey.data;

  return (
    <div className="space-y-4">
      <ol className="flex flex-wrap gap-3 text-sm">
        {(Object.keys(STEP_LABEL) as Step[]).map((s) => (
          <li key={s} className={s === step ? "font-semibold text-blue-700" : "text-slate-500"}>{STEP_LABEL[s]}</li>
        ))}
      </ol>
      {studyCode && step !== "patient" && (
        <p className="text-sm">
          Patient <span className="font-mono">{studyCode}</span>
          {template && step !== "template" ? ` · ${template.title}` : ""}
        </p>
      )}
      {step === "patient" && (
        <PatientStep
          cryptoKey={key.cryptoKey}
          onDone={(code) => {
            setStudyCode(code);
            setStep("template");
          }}
        />
      )}
      {step === "template" && (
        <TemplateStep
          onBack={() => setStep("patient")}
          onDone={(t) => {
            setTemplate(t);
            setStep("photos");
          }}
        />
      )}
      {step === "photos" && <PhotosStep pages={pages} onChange={setPages} onBack={() => setStep("template")} onNext={() => setStep("redact")} />}
    </div>
  );
}
```

In `web/src/App.tsx`, add the import

```tsx
import CapturePage from "./capture/CapturePage";
```

and add this line above `<Route path="*" …>`:

```tsx
      <Route path="capture" element={<CapturePage />} />
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm run typecheck && npm test && npm run e2e`
Expected: all pass; Playwright reports `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add web/src/capture web/src/App.tsx web/e2e
git commit -m "feat(web): capture wizard — study code, form choice, photos with crop and blur check" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Hide names on the phone, then upload

**Files:**
- Create: `web/src/imaging/useHtmlImage.ts`, `web/src/capture/RedactionCanvas.tsx`, `web/src/capture/RedactStep.tsx`
- Modify: `web/src/capture/CapturePage.tsx` (render the redact step), `web/e2e/flow.spec.ts` (append test)

**Interfaces:**
- Consumes: `ocrLines`, `suggestBoxes` (Task 4); `burnRedactions` (Task 4); `enqueue`, `flushOutbox`, `useOutbox` (Task 5); `PageDraft` (Task 6).
- Produces:
  - `useHtmlImage(url) -> HTMLImageElement | null`.
  - `RedactionCanvas` (boxes in page-pixel coordinates, drawn at 85% opacity while editing).
  - `RedactStep`. On success it navigates to `/records/{id}` with router state `{ duplicateOf }`. If the upload is queued it goes home with state `{ notice }`. If the server refuses it, the reason is shown in place.
  - Accessible names: text `Finding names…` while OCR runs, test id `box-count` (`"N box"` / `"N boxes"`), buttons `Add box`, `Delete box`, `Upload`, `Back`, and checkbox label `All names and numbers are covered.`

- [ ] **Step 1: Write the failing e2e test**

Append to `web/e2e/flow.spec.ts`. The test checks the uploaded pixels themselves: the name and phone lines must be black, and the findings must still be readable.

```ts
let recordId = "";

async function brightness(fileUrl: string, x: number, y: number, w: number, h: number): Promise<number> {
  return page.evaluate(
    async ({ fileUrl, x, y, w, h }) => {
      const bitmap = await createImageBitmap(await (await fetch(fileUrl)).blob());
      const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
      const ctx = canvas.getContext("2d")!;
      ctx.drawImage(bitmap, 0, 0);
      const data = ctx.getImageData(x, y, w, h).data;
      let sum = 0;
      for (let i = 0; i < data.length; i += 4) sum += (data[i] + data[i + 1] + data[i + 2]) / 3;
      return sum / (data.length / 4);
    },
    { fileUrl, x, y, w, h },
  );
}

test("names are boxed on the device and only the redacted page is uploaded", async () => {
  await page.getByRole("button", { name: "Next: hide names" }).click();
  await expect(page.getByText("Finding names…")).toBeHidden({ timeout: 90_000 });
  await expect(page.getByTestId("box-count")).not.toHaveText("0 boxes");
  const upload = page.getByRole("button", { name: "Upload" });
  await expect(upload).toBeDisabled();
  await page.getByLabel("All names and numbers are covered.").check();
  await upload.click();
  await expect(page).toHaveURL(/\/records\/[0-9a-f-]{36}$/);
  recordId = page.url().split("/").pop()!;

  const record = await page.evaluate(async (id) => (await fetch(`/api/records/${id}`)).json(), recordId);
  expect(record.study_code).toBe(studyCode);
  const fileUrl = `/api/files/${record.files[0].id}`;
  expect(await brightness(fileUrl, 70, 175, 330, 20)).toBeLessThan(40); // "Patient Name: …" is black
  expect(await brightness(fileUrl, 70, 275, 330, 20)).toBeLessThan(40); // "Mobile: 017…" is black
  expect(await brightness(fileUrl, 60, 740, 1600, 80)).toBeGreaterThan(150); // findings stay readable
});
```

Run: `cd web && npm run e2e`
Expected: the new test FAILS because clicking "Next: hide names" shows nothing yet.

- [ ] **Step 2: Implement the image hook and the box editor**

`web/src/imaging/useHtmlImage.ts`:

```ts
import { useEffect, useState } from "react";

export function useHtmlImage(url: string): HTMLImageElement | null {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    const img = new window.Image();
    img.onload = () => setImage(img);
    img.src = url;
    return () => {
      img.onload = null;
    };
  }, [url]);
  return image;
}
```

`web/src/capture/RedactionCanvas.tsx`:

```tsx
import type Konva from "konva";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Image as KonvaImage, Layer, Rect as KonvaRect, Stage, Transformer } from "react-konva";
import type { Rect } from "../imaging/geometry";
import { useHtmlImage } from "../imaging/useHtmlImage";

interface Props {
  url: string;
  width: number;
  height: number;
  boxes: Rect[];
  disabled: boolean;
  selected: number | null;
  onSelect: (index: number | null) => void;
  onChange: (boxes: Rect[]) => void;
}

export function RedactionCanvas({ url, width, height, boxes, disabled, selected, onSelect, onChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const transformerRef = useRef<Konva.Transformer>(null);
  const shapes = useRef(new Map<number, Konva.Rect>());
  const image = useHtmlImage(url);
  const [displayWidth, setDisplayWidth] = useState(0);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setDisplayWidth(Math.min(el.clientWidth, 900));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const scale = displayWidth > 0 ? displayWidth / width : 0;

  useEffect(() => {
    const transformer = transformerRef.current;
    if (!transformer) return;
    const node = selected === null ? undefined : shapes.current.get(selected);
    transformer.nodes(node && !disabled ? [node] : []);
    transformer.getLayer()?.batchDraw();
  }, [selected, boxes, disabled, scale]);

  const update = (index: number, box: Rect) => onChange(boxes.map((b, i) => (i === index ? box : b)));
  const deselectOnBackground = (e: Konva.KonvaEventObject<Event>) => {
    if (e.target === e.target.getStage() || e.target.getClassName() === "Image") onSelect(null);
  };

  return (
    <div ref={containerRef} className="w-full">
      {scale > 0 && image && (
        <Stage width={displayWidth} height={Math.round(height * scale)} onMouseDown={deselectOnBackground} onTouchStart={deselectOnBackground}>
          <Layer>
            <KonvaImage image={image} width={displayWidth} height={Math.round(height * scale)} />
            {boxes.map((box, i) => (
              <KonvaRect
                key={i}
                ref={(node) => {
                  if (node) shapes.current.set(i, node);
                  else shapes.current.delete(i);
                }}
                x={box.x * scale}
                y={box.y * scale}
                width={box.w * scale}
                height={box.h * scale}
                fill="black"
                opacity={0.85}
                stroke={i === selected ? "#dc2626" : undefined}
                strokeWidth={2}
                draggable={!disabled}
                onMouseDown={() => onSelect(i)}
                onTouchStart={() => onSelect(i)}
                onDragEnd={(e) => update(i, { ...box, x: e.target.x() / scale, y: e.target.y() / scale })}
                onTransformEnd={(e) => {
                  const node = e.target;
                  const w = (node.width() * node.scaleX()) / scale;
                  const h = (node.height() * node.scaleY()) / scale;
                  node.scaleX(1);
                  node.scaleY(1);
                  update(i, { x: node.x() / scale, y: node.y() / scale, w, h });
                }}
              />
            ))}
            <Transformer ref={transformerRef} rotateEnabled={false} keepRatio={false} />
          </Layer>
        </Stage>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Implement the redact step**

`web/src/capture/RedactStep.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import type { Rect } from "../imaging/geometry";
import { burnRedactions } from "../imaging/render";
import { useOutbox } from "../outbox/OutboxContext";
import { enqueue, flushOutbox, type SendResult } from "../outbox/outbox";
import { suggestBoxes } from "../redaction/labels";
import { ocrLines } from "../redaction/ocr";
import type { OutboxMeta } from "../storage/idb";
import { primaryButton, secondaryButton } from "../ui/styles";
import { RedactionCanvas } from "./RedactionCanvas";
import type { PageDraft } from "./types";

interface Props {
  pages: PageDraft[];
  onChange: (pages: PageDraft[]) => void;
  meta: OutboxMeta;
  onBack: () => void;
}

export function RedactStep({ pages, onChange, meta, onBack }: Props) {
  const navigate = useNavigate();
  const outbox = useOutbox();
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [ocrBusy, setOcrBusy] = useState(() => pages.some((p) => !p.ocrDone));
  const [ocrWarning, setOcrWarning] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Suggest boxes once per page, on this device only. Editing is disabled until this finishes.
  useEffect(() => {
    const pending = pages.filter((p) => !p.ocrDone);
    if (pending.length === 0) return;
    let cancelled = false;
    void (async () => {
      let next = pages;
      for (const page of pending) {
        let found: Rect[] = [];
        try {
          found = suggestBoxes(await ocrLines(page.blob));
        } catch {
          setOcrWarning("Automatic name finding failed — draw the boxes by hand.");
        }
        if (cancelled) return;
        next = next.map((p) => (p.id === page.id ? { ...p, boxes: [...p.boxes, ...found], ocrDone: true } : p));
      }
      onChange(next);
      setOcrBusy(false);
    })();
    return () => {
      cancelled = true;
    };
    // Runs once when the step opens; `pages` cannot change while OCR is running because editing is disabled.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const page = pages[Math.min(index, pages.length - 1)];
  const setBoxes = (boxes: Rect[]) => onChange(pages.map((p) => (p.id === page.id ? { ...p, boxes } : p)));

  function addBox() {
    setBoxes([...page.boxes, { x: page.width * 0.1, y: page.height * 0.1, w: page.width * 0.4, h: page.height * 0.06 }]);
    setSelected(page.boxes.length);
  }

  function deleteBox() {
    if (selected === null) return;
    setBoxes(page.boxes.filter((_, i) => i !== selected));
    setSelected(null);
  }

  async function upload() {
    setUploading(true);
    setError(null);
    try {
      const redacted = await Promise.all(pages.map((p) => burnRedactions(p.blob, p.boxes)));
      const item = await enqueue(meta, redacted);
      let result: SendResult | undefined = (await flushOutbox()).get(item.id);
      if (!result) result = (await flushOutbox()).get(item.id); // a flush that started earlier did not include it
      await outbox.refresh();
      if (result?.outcome === "done" && result.recordId) {
        navigate(`/records/${result.recordId}`, { state: { duplicateOf: result.duplicateOf ?? [] } });
      } else if (result?.outcome === "fail") {
        setError(`Upload refused: ${result.error}. The redacted copy is listed on the home screen.`);
      } else {
        navigate("/", { state: { notice: "Saved on this device — it will upload when the connection is back." } });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  const count = page.boxes.length;
  const locked = ocrBusy || uploading;
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Hide names and numbers</h2>
      <p className="text-sm text-slate-600">
        Black boxes are burned into the photo before it leaves this device. Cover every patient name, phone number, address and ID.
      </p>
      {ocrBusy && <p className="rounded-md bg-slate-100 p-3">Finding names…</p>}
      {ocrWarning && <p className="rounded-md bg-amber-50 p-3 text-amber-900">{ocrWarning}</p>}
      {pages.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {pages.map((p, i) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setIndex(i);
                setSelected(null);
              }}
              className={i === index ? primaryButton : secondaryButton}
            >
              Page {i + 1}
            </button>
          ))}
        </div>
      )}
      <RedactionCanvas url={page.url} width={page.width} height={page.height} boxes={page.boxes} disabled={locked} selected={selected} onSelect={setSelected} onChange={setBoxes} />
      <p data-testid="box-count" className="text-sm">
        {count} {count === 1 ? "box" : "boxes"}
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={locked} onClick={addBox} className={secondaryButton}>Add box</button>
        <button type="button" disabled={selected === null || locked} onClick={deleteBox} className={secondaryButton}>Delete box</button>
      </div>
      <label className="flex items-start gap-2">
        <input type="checkbox" checked={confirmed} disabled={ocrBusy} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1" />
        <span>All names and numbers are covered.</span>
      </label>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={uploading} onClick={onBack} className={secondaryButton}>Back</button>
        <button type="button" disabled={!confirmed || locked} onClick={upload} className={primaryButton}>
          {uploading ? "Uploading…" : "Upload"}
        </button>
      </div>
    </div>
  );
}
```

In `web/src/capture/CapturePage.tsx`, add the import `import { RedactStep } from "./RedactStep";` and add this line after the `PhotosStep` line:

```tsx
      {step === "redact" && studyCode && template && (
        <RedactStep
          pages={pages}
          onChange={setPages}
          onBack={() => setStep("photos")}
          meta={{ study_code: studyCode, template_key: template.key, key_fingerprint: key.fingerprint }}
        />
      )}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm run typecheck && npm test && npm run e2e`
Expected: all pass; Playwright reports `4 passed`. The redacted lines have brightness below 40.

- [ ] **Step 5: Look at the uploaded image yourself once**

With both dev servers running (`cd server && uv run python -m capture.devserver`, `cd web && npm run dev`), capture `web/e2e/fixtures/report.jpg` as `uploader@amcgh.test`. After upload, open `/api/files/<id>` in the same browser. Check that the name, phone and registration-number lines are solid black and the findings are readable.

- [ ] **Step 6: Commit**

```bash
git add web/src web/e2e
git commit -m "feat(web): on-device redaction with OCR-suggested boxes, upload through the outbox" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Form renderer and review permissions

**Files:**
- Create: `web/src/records/fieldPaths.ts`, `web/src/records/permissions.ts`, `web/src/records/FormRenderer.tsx`
- Test: `web/src/records/fieldPaths.test.ts`, `web/src/records/permissions.test.ts`, `web/src/records/FormRenderer.test.tsx`

**Interfaces:**
- Consumes: `FieldDef`, `Role`, `Status` (Task 2); `isHospital` (Task 2); `inputClass`, `card`, `secondaryButton` (Task 2).
- Produces:
  - `fieldPaths.ts`: `PathPart = string|number`, `pathToString(parts)` (gives `lesions[0].lobe`), `getIn(obj, parts)`, `setIn(obj, parts, value)` (immutable), `humanize(key)`.
  - `permissions.ts`: `canEdit(role, status)` (same rule as the server), `UiAction = "submit"|"approve"|"return"|"reopen"`, `availableActions(role, status, isCreator) -> UiAction[]`.
  - `FormRenderer {fields, values, onChange, errors: Record<path,string>, readOnly, flags?}`. Labels are linked to inputs, so `getByLabel("Long axis")` works. Each repeat group has an `Add <label>` button and `Remove <label> N` buttons. Empty inputs store `null`. Number inputs keep what was typed, so `2.` survives; text that is not a number is passed on as a string.

- [ ] **Step 1: Write the failing tests**

`web/src/records/fieldPaths.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { getIn, humanize, pathToString, setIn } from "./fieldPaths";

describe("field paths", () => {
  it("formats paths like the server", () => {
    expect(pathToString(["lesions", 0, "long_axis_cm"])).toBe("lesions[0].long_axis_cm");
    expect(pathToString(["modality"])).toBe("modality");
  });
  it("reads nested values", () => {
    expect(getIn({ lesions: [{ lobe: "RUL" }] }, ["lesions", 0, "lobe"])).toBe("RUL");
    expect(getIn({}, ["lesions", 0, "lobe"])).toBeUndefined();
  });
  it("writes nested values without mutating the original", () => {
    const original = { modality: "CT", lesions: [{ lobe: "RUL" }] };
    const next = setIn(original, ["lesions", 1, "lobe"], "LUL");
    expect(next).toEqual({ modality: "CT", lesions: [{ lobe: "RUL" }, { lobe: "LUL" }] });
    expect(original.lesions).toHaveLength(1);
  });
  it("humanizes keys", () => {
    expect(humanize("long_axis_cm")).toBe("Long axis cm");
  });
});
```

`web/src/records/permissions.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { availableActions, canEdit } from "./permissions";

describe("canEdit", () => {
  it.each([
    ["uploader", "draft", true],
    ["uploader", "pending_doctor", false],
    ["hospital_doctor", "draft", true],
    ["hospital_doctor", "pending_doctor", true],
    ["hospital_doctor", "pending_nsu", false],
    ["nsu_reviewer", "pending_nsu", false],
    ["admin", "approved", false],
  ] as const)("%s on %s -> %s", (role, status, expected) => {
    expect(canEdit(role, status)).toBe(expected);
  });
});

describe("availableActions", () => {
  it("lets hospital staff submit drafts", () => {
    expect(availableActions("uploader", "draft", true)).toEqual(["submit"]);
  });
  it("lets another doctor approve or return", () => {
    expect(availableActions("hospital_doctor", "pending_doctor", false)).toEqual(["approve", "return"]);
  });
  it("hides approve from the doctor who uploaded the record", () => {
    expect(availableActions("hospital_doctor", "pending_doctor", true)).toEqual(["return"]);
  });
  it("lets the NSU reviewer approve or return", () => {
    expect(availableActions("nsu_reviewer", "pending_nsu", false)).toEqual(["approve", "return"]);
  });
  it("lets an admin reopen approved records", () => {
    expect(availableActions("admin", "approved", false)).toEqual(["reopen"]);
  });
  it("offers nothing otherwise", () => {
    expect(availableActions("uploader", "pending_doctor", true)).toEqual([]);
    expect(availableActions("admin", "pending_nsu", false)).toEqual([]);
  });
});
```

`web/src/records/FormRenderer.test.tsx`:

```tsx
// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
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
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL with `Failed to resolve import "./fieldPaths"`, `"./permissions"` and `"./FormRenderer"`.

- [ ] **Step 3: Implement paths and permissions**

`web/src/records/fieldPaths.ts`:

```ts
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
```

`web/src/records/permissions.ts`:

```ts
import type { Role, Status } from "../api/types";
import { isHospital } from "../auth/roles";

/** Mirrors capture.workflow.rules.can_edit on the server. */
export function canEdit(role: Role, status: Status): boolean {
  if (role === "uploader") return status === "draft";
  if (role === "hospital_doctor") return status === "draft" || status === "pending_doctor";
  return false;
}

export type UiAction = "submit" | "approve" | "return" | "reopen";

export function availableActions(role: Role, status: Status, isCreator: boolean): UiAction[] {
  if (status === "draft" && isHospital(role)) return ["submit"];
  if (status === "pending_doctor" && role === "hospital_doctor") return isCreator ? ["return"] : ["approve", "return"];
  if (status === "pending_nsu" && role === "nsu_reviewer") return ["approve", "return"];
  if (status === "approved" && role === "admin") return ["reopen"];
  return [];
}
```

- [ ] **Step 4: Implement the form renderer**

`web/src/records/FormRenderer.tsx`:

```tsx
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

/** "" -> null, numeric text -> number, anything else stays text so the server can flag it. */
function parseNumber(text: string): unknown {
  if (text.trim() === "") return null;
  const n = Number(text);
  return Number.isNaN(n) ? text : n;
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npm test && npm run typecheck`
Expected: all pass, `tsc` clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/records
git commit -m "feat(web): template-driven form renderer and review permissions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Record review page — photo beside the form

**Files:**
- Create: `web/src/ui/StatusBadge.tsx`, `web/src/records/PageViewer.tsx`, `web/src/records/RecordPage.tsx`
- Modify: `web/src/App.tsx` (add route), `web/e2e/flow.spec.ts` (append test)

**Interfaces:**
- Consumes: `useRecord`, `api`, `ApiError`, `json` (Task 2); `FormRenderer`, `canEdit`, `availableActions`, `UiAction` (Task 8).
- Produces:
  - `STATUS_LABEL`, and `StatusBadge` with `data-testid="record-status"` and labels `Draft`, `Waiting for doctor`, `Waiting for NSU`, `Approved`, `Processing`, `Quarantined`.
  - Route `/records/:id`.
  - Accessible names:
    - Buttons `Save`, `Submit for doctor review`, `Approve`, `Return…`, `Reopen…`, `Confirm`, `Cancel`.
    - Text-area labels `What needs fixing?` and `Reason for reopening`.
    - A `role="status"` message after each action (`Saved`, `Submitted for doctor review`, `Approved`, `Returned to the uploader`, `Reopened`).
    - Page images with alt text `Page N`.

- [ ] **Step 1: Write the failing e2e test**

Append to `web/e2e/flow.spec.ts`:

```ts
test("the uploader fills the form, sees a validation error, fixes it and submits", async () => {
  await page.goto(`/records/${recordId}`);
  await expect(page.getByRole("heading", { name: /Radiology report/ })).toBeVisible();
  await expect(page.getByRole("img", { name: "Page 1" })).toBeVisible();
  await expect(page.getByTestId("record-status")).toHaveText("Draft");
  await page.getByLabel("Modality").selectOption("CT");
  await page.getByLabel("Study date").fill("2026-09-01");
  await page.getByRole("button", { name: "Add lesion" }).click();
  await page.getByLabel("Lobe").selectOption("RUL");
  await page.getByLabel("Long axis").fill("abc");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("must be a number")).toBeVisible();
  await page.getByLabel("Long axis").fill("2.");
  await page.getByLabel("Long axis").pressSequentially("3");
  await expect(page.getByLabel("Long axis")).toHaveValue("2.3");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  await expect(page.getByText("must be a number")).toHaveCount(0);
  await page.getByRole("button", { name: "Submit for doctor review" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for doctor");
  await expect(page.getByLabel("Modality")).toBeDisabled();
  await logout();
});
```

Run: `cd web && npm run e2e`
Expected: the new test FAILS because `/records/:id` shows "Page not found."

- [ ] **Step 2: Implement the status badge and page viewer**

`web/src/ui/StatusBadge.tsx`:

```tsx
import type { Status } from "../api/types";

export const STATUS_LABEL: Record<Status, string> = {
  processing: "Processing",
  quarantined: "Quarantined",
  draft: "Draft",
  pending_doctor: "Waiting for doctor",
  pending_nsu: "Waiting for NSU",
  approved: "Approved",
};

const COLOUR: Record<Status, string> = {
  processing: "bg-slate-100 text-slate-700",
  quarantined: "bg-red-100 text-red-800",
  draft: "bg-slate-100 text-slate-800",
  pending_doctor: "bg-amber-100 text-amber-800",
  pending_nsu: "bg-sky-100 text-sky-800",
  approved: "bg-green-100 text-green-800",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span data-testid="record-status" className={`rounded px-2 py-0.5 text-sm font-medium ${COLOUR[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}
```

`web/src/records/PageViewer.tsx`:

```tsx
import { useState } from "react";
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";
import type { FileOut } from "../api/types";
import { card, secondaryButton } from "../ui/styles";

export function PageViewer({ files }: { files: FileOut[] }) {
  const pages = files.filter((f) => f.kind === "page");
  const [index, setIndex] = useState(0);
  if (pages.length === 0) return <p className={card}>No images.</p>;
  const current = Math.min(index, pages.length - 1);
  const file = pages[current];
  return (
    <details open className={`${card} space-y-2 self-start`}>
      <summary className="cursor-pointer font-medium">
        Page {current + 1} of {pages.length} — pinch or scroll to zoom
      </summary>
      <TransformWrapper key={file.id}>
        <TransformComponent wrapperClass="!w-full" contentClass="!w-full">
          <img src={`/api/files/${file.id}`} alt={`Page ${current + 1}`} className="w-full" />
        </TransformComponent>
      </TransformWrapper>
      {pages.length > 1 && (
        <div className="flex gap-2">
          <button type="button" disabled={current === 0} onClick={() => setIndex(current - 1)} className={secondaryButton}>Previous</button>
          <button type="button" disabled={current === pages.length - 1} onClick={() => setIndex(current + 1)} className={secondaryButton}>Next</button>
        </div>
      )}
    </details>
  );
}
```

- [ ] **Step 3: Implement the record page**

`web/src/records/RecordPage.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { ApiError, api, json } from "../api/client";
import { useRecord } from "../api/hooks";
import type { EventOut, RecordDetail } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { StatusBadge } from "../ui/StatusBadge";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";
import { FormRenderer } from "./FormRenderer";
import { PageViewer } from "./PageViewer";
import { availableActions, canEdit, type UiAction } from "./permissions";

const DONE: Record<UiAction, string> = {
  submit: "Submitted for doctor review",
  approve: "Approved",
  return: "Returned to the uploader",
  reopen: "Reopened",
};

const EVENT_LABEL: Record<string, string> = {
  upload: "uploaded",
  edit: "edited",
  submit: "submitted",
  approve: "approved",
  return: "returned",
  reopen: "reopened",
};

export default function RecordPage() {
  const { id = "" } = useParams();
  const record = useRecord(id);
  if (record.isPending) return <p>Loading…</p>;
  if (record.isError) return <p role="alert" className="text-red-700">{record.error.message}</p>;
  return <RecordView key={record.data.id} record={record.data} />;
}

function RecordView({ record: r }: { record: RecordDetail }) {
  const me = useCurrentUser();
  const queryClient = useQueryClient();
  const location = useLocation();
  const duplicateOf = (location.state as { duplicateOf?: string[] } | null)?.duplicateOf ?? [];
  const [values, setValues] = useState(r.values);
  const [syncedVersion, setSyncedVersion] = useState(r.row_version);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [dialog, setDialog] = useState<"return" | "reopen" | null>(null);
  const [comment, setComment] = useState("");

  // When the server copy changes (save, action, reload), show its values.
  if (syncedVersion !== r.row_version) {
    setSyncedVersion(r.row_version);
    setValues(r.values);
  }

  const editable = canEdit(me.role, r.status);
  const dirty = JSON.stringify(values) !== JSON.stringify(r.values);
  const actions = availableActions(me.role, r.status, r.created_by_id === me.id);
  const errors = Object.fromEntries(r.errors.map((e) => [e.path, e.message]));
  const lastReturn = r.status === "draft" ? [...r.events].reverse().find((e) => e.action === "return" || e.action === "reopen") : undefined;

  function store(updated: RecordDetail) {
    queryClient.setQueryData(["record", updated.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["records"] });
  }

  async function save(): Promise<boolean> {
    try {
      store(await api<RecordDetail>(`/records/${r.id}/values`, { method: "PATCH", body: json({ row_version: r.row_version, values }) }));
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(true);
      else setMessage(e instanceof Error ? e.message : "Save failed");
      return false;
    }
  }

  async function onSave() {
    setBusy(true);
    setMessage(null);
    if (await save()) setMessage("Saved");
    setBusy(false);
  }

  async function run(action: UiAction, withComment?: string) {
    setBusy(true);
    setMessage(null);
    try {
      if (editable && dirty && !(await save())) return;
      store(await api<RecordDetail>(`/records/${r.id}/transition`, { method: "POST", body: json({ action, comment: withComment ?? null }) }));
      setDialog(null);
      setComment("");
      setMessage(DONE[action]);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">{r.template_title}</h1>
        <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
          <span>
            Study code <span className="font-mono">{r.study_code}</span>
          </span>
          <StatusBadge status={r.status} />
          <span>Uploaded by {r.created_by_name}</span>
        </p>
      </header>

      {duplicateOf.length > 0 && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">
          This looks already uploaded for this patient:
          {duplicateOf.map((d) => (
            <Link key={d} to={`/records/${d}`} className="ml-2 underline">
              {d.slice(0, 8)}
            </Link>
          ))}
        </p>
      )}
      {lastReturn && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">
          Returned by {lastReturn.actor_name}: {lastReturn.comment}
        </p>
      )}
      {r.status === "processing" && <p className="rounded-md bg-slate-100 p-3">The AI is reading this document…</p>}
      {conflict && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-red-800">
          Someone else changed this record — reload
          <button
            type="button"
            className={`${secondaryButton} ml-2`}
            onClick={() => {
              setConflict(false);
              void queryClient.invalidateQueries({ queryKey: ["record", r.id] });
            }}
          >
            Reload
          </button>
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <PageViewer files={r.files} />
        <div className="space-y-4">
          <FormRenderer fields={r.template.definition.fields} values={values} onChange={setValues} errors={errors} readOnly={!editable} flags={lastReturn?.field_flags ?? {}} />
          <div className="flex flex-wrap gap-2">
            {editable && (
              <button type="button" disabled={busy || !dirty} onClick={onSave} className={secondaryButton}>
                Save
              </button>
            )}
            {actions.includes("submit") && (
              <button type="button" disabled={busy} onClick={() => run("submit")} className={primaryButton}>
                Submit for doctor review
              </button>
            )}
            {actions.includes("approve") && (
              <button type="button" disabled={busy} onClick={() => run("approve")} className={primaryButton}>
                Approve
              </button>
            )}
            {actions.includes("return") && (
              <button type="button" disabled={busy} onClick={() => setDialog("return")} className={secondaryButton}>
                Return…
              </button>
            )}
            {actions.includes("reopen") && (
              <button type="button" disabled={busy} onClick={() => setDialog("reopen")} className={secondaryButton}>
                Reopen…
              </button>
            )}
          </div>
          {me.role === "hospital_doctor" && r.status === "pending_doctor" && r.created_by_id === me.id && (
            <p className="text-sm text-slate-600">You uploaded this record, so another doctor must approve it.</p>
          )}
          {dialog && (
            <div className={`${card} space-y-2`}>
              <label className="block text-sm font-medium">
                {dialog === "return" ? "What needs fixing?" : "Reason for reopening"}
                <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} className={inputClass} />
              </label>
              <div className="flex gap-2">
                <button type="button" disabled={busy || !comment.trim()} onClick={() => run(dialog, comment)} className={primaryButton}>
                  Confirm
                </button>
                <button type="button" onClick={() => setDialog(null)} className={secondaryButton}>
                  Cancel
                </button>
              </div>
            </div>
          )}
          {message && (
            <p role="status" className="text-sm">
              {message}
            </p>
          )}
        </div>
      </div>
      <History events={r.events} />
    </div>
  );
}

function History({ events }: { events: EventOut[] }) {
  return (
    <section className={card}>
      <h2 className="mb-2 font-semibold">History</h2>
      <ol className="space-y-1 text-sm">
        {events.map((e) => (
          <li key={e.id}>
            {new Date(e.created_at).toLocaleString()} — {e.actor_name} {EVENT_LABEL[e.action] ?? e.action}
            {e.action === "edit" && e.field_changes ? ` ${e.field_changes.length} field(s)` : ""}
            {e.comment ? `: ${e.comment}` : ""}
          </li>
        ))}
      </ol>
    </section>
  );
}
```

In `web/src/App.tsx`, add the import `import RecordPage from "./records/RecordPage";` and add this line above `<Route path="*" …>`:

```tsx
      <Route path="records/:id" element={<RecordPage />} />
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm run typecheck && npm test && npm run e2e`
Expected: all pass; Playwright reports `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add web/src web/e2e
git commit -m "feat(web): record review page with zoomable photo, form, actions and history" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Home screen, approval queues and the full approval story

**Files:**
- Create: `web/src/ui/time.ts`, `web/src/records/RecordList.tsx`, `web/src/queues/QueuePage.tsx`
- Replace: `web/src/home/HomePage.tsx`
- Modify: `web/src/App.tsx` (add route), `web/e2e/flow.spec.ts` (append tests)
- Test: `web/src/ui/time.test.ts`

**Interfaces:**
- Consumes: `useRecords` (Task 2), `useDeviceKey` (Task 3), `useOutbox` (Task 5), `isHospital` (Task 2).
- Produces:
  - `ageLabel(iso, now?) -> "just now" | "N min" | "N h" | "N d"`.
  - `RecordList {records, empty}`. Each row links to `/records/{id}` and shows title, study code, date, uploader and age, plus a `Returned` badge for drafts whose last event is a return.
  - Route `/queue/:stage`, where `stage` is `doctor` (hospital_doctor) or `nsu` (nsu_reviewer, admin), listed oldest first.
  - Hospital home: `New capture`, device key status, outbox (waiting count + `Try now`; refused items with the reason + `Discard`), the doctor queue count, and `My drafts`. NSU home: queue count.

- [ ] **Step 1: Write the failing tests**

`web/src/ui/time.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ageLabel } from "./time";

const NOW = new Date("2026-10-04T12:00:00Z");

describe("ageLabel", () => {
  it.each([
    ["2026-10-04T11:59:40Z", "just now"],
    ["2026-10-04T11:45:00Z", "15 min"],
    ["2026-10-04T09:00:00Z", "3 h"],
    ["2026-10-02T13:00:00Z", "47 h"],
    ["2026-10-02T12:00:00Z", "2 d"],
    ["2026-09-30T12:00:00Z", "4 d"],
  ])("%s -> %s", (iso, label) => {
    expect(ageLabel(iso, NOW)).toBe(label);
  });
});
```

Append to `web/e2e/flow.spec.ts`:

```ts
async function openFromQueue(queueLink: string) {
  await page.getByRole("link", { name: queueLink }).click();
  await page.getByRole("link", { name: new RegExp(studyCode) }).click();
}

test("a second hospital doctor approves from the doctor queue", async () => {
  await login("doctor2@amcgh.test");
  await openFromQueue("Doctor queue");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for NSU");
  await logout();
});

test("NSU returns the record with a comment and the uploader sees it on the home screen", async () => {
  await login("reviewer@nsu.test");
  await openFromQueue("NSU queue");
  await page.getByRole("button", { name: "Return…" }).click();
  await page.getByLabel("What needs fixing?").fill("Please add the short axis");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("status")).toHaveText("Returned to the uploader");
  await logout();

  await login("uploader@amcgh.test");
  await expect(page.getByText("Returned", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: new RegExp(studyCode) }).click();
  await expect(page.getByText("Please add the short axis")).toBeVisible();
  await page.getByLabel("Short axis").fill("1.8");
  await page.getByRole("button", { name: "Submit for doctor review" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for doctor");
  await logout();
});

test("after the doctor and NSU approve again, the record is approved", async () => {
  await login("doctor2@amcgh.test");
  await openFromQueue("Doctor queue");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for NSU");
  await logout();

  await login("reviewer@nsu.test");
  await openFromQueue("NSU queue");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Approved");
  await logout();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL with `Failed to resolve import "./time"`.

Run: `cd web && npm run e2e`
Expected: the queue tests FAIL because `/queue/doctor` shows "Page not found."

- [ ] **Step 3: Implement the time label and the record list**

`web/src/ui/time.ts`:

```ts
export function ageLabel(iso: string, now: Date = new Date()): string {
  const minutes = Math.floor((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.floor(hours / 24)} d`;
}
```

`web/src/records/RecordList.tsx`:

```tsx
import { Link } from "react-router";
import type { RecordSummary } from "../api/types";
import { ageLabel } from "../ui/time";

export function RecordList({ records, empty }: { records: RecordSummary[]; empty: string }) {
  if (records.length === 0) return <p className="text-slate-500">{empty}</p>;
  return (
    <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
      {records.map((r) => (
        <li key={r.id}>
          <Link to={`/records/${r.id}`} className="flex items-start justify-between gap-3 p-3 hover:bg-slate-50">
            <span>
              <span className="block font-medium">{r.template_title}</span>
              <span className="font-mono text-sm">{r.study_code}</span>
              <span className="text-sm text-slate-600"> · {r.document_date ?? "no date yet"}</span>
            </span>
            <span className="text-right text-sm text-slate-600">
              {r.status === "draft" && r.last_event?.action === "return" && (
                <span className="mb-1 inline-block rounded bg-amber-100 px-2 text-amber-800">Returned</span>
              )}
              <span className="block">{r.created_by_name}</span>
              <span className="block">{ageLabel(r.updated_at)}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: Implement the queue page and the home screen**

`web/src/queues/QueuePage.tsx`:

```tsx
import { useParams } from "react-router";
import { useRecords } from "../api/hooks";
import type { Role } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { RecordList } from "../records/RecordList";

const QUEUES: Record<string, { status: string; title: string; roles: Role[] }> = {
  doctor: { status: "pending_doctor", title: "Waiting for doctor approval", roles: ["hospital_doctor"] },
  nsu: { status: "pending_nsu", title: "Waiting for NSU approval", roles: ["nsu_reviewer", "admin"] },
};

export default function QueuePage() {
  const { stage = "" } = useParams();
  const me = useCurrentUser();
  const queue = QUEUES[stage];
  const allowed = queue !== undefined && queue.roles.includes(me.role);
  const records = useRecords({ status: queue?.status }, allowed);

  if (!queue) return <p>Unknown queue.</p>;
  if (!allowed) return <p>This queue is not available for your role.</p>;
  const oldestFirst = [...(records.data ?? [])].sort((a, b) => a.updated_at.localeCompare(b.updated_at));
  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold">{queue.title}</h1>
      {records.isPending ? <p>Loading…</p> : <RecordList records={oldestFirst} empty="Nothing waiting." />}
    </section>
  );
}
```

`web/src/home/HomePage.tsx` (replace the whole file):

```tsx
import { Link, useLocation } from "react-router";
import { useRecords } from "../api/hooks";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";
import { useDeviceKey } from "../crypto/keyStore";
import { useOutbox } from "../outbox/OutboxContext";
import { RecordList } from "../records/RecordList";
import { card, secondaryButton } from "../ui/styles";

export default function HomePage() {
  const me = useCurrentUser();
  const location = useLocation();
  const notice = (location.state as { notice?: string } | null)?.notice;
  return (
    <div className="space-y-6">
      {notice && (
        <p role="status" className="rounded-md bg-sky-50 p-3 text-sky-900">
          {notice}
        </p>
      )}
      {isHospital(me.role) ? <HospitalHome /> : <NsuHome />}
    </div>
  );
}

function HospitalHome() {
  const me = useCurrentUser();
  const deviceKey = useDeviceKey();
  const outbox = useOutbox();
  const drafts = useRecords({ status: "draft", mine: true });
  const doctorQueue = useRecords({ status: "pending_doctor" }, me.role === "hospital_doctor");
  const waiting = outbox.items.filter((item) => !item.failed);
  const refused = outbox.items.filter((item) => item.failed);

  return (
    <>
      <Link to="/capture" className="block rounded-xl bg-blue-700 p-6 text-center text-xl font-semibold text-white hover:bg-blue-800">
        New capture
      </Link>
      <p className="text-sm text-slate-600">
        {deviceKey.data ? (
          <>
            Device key <span className="font-mono">{deviceKey.data.fingerprint}</span>
          </>
        ) : me.role === "hospital_doctor" ? (
          <>
            This device has no hospital key — <Link to="/setup" className="underline">set it up</Link>.
          </>
        ) : (
          "This device has no hospital key — ask a hospital doctor to set it up."
        )}
      </p>
      {waiting.length > 0 && (
        <div className={card}>
          <p>{waiting.length} waiting to upload</p>
          <button type="button" onClick={() => void outbox.flush()} className={`${secondaryButton} mt-2`}>
            Try now
          </button>
        </div>
      )}
      {refused.map((item) => (
        <div key={item.id} className="rounded-md bg-red-50 p-3 text-red-900">
          <p>
            Upload refused for {item.meta.study_code}: {item.error}
          </p>
          <button type="button" onClick={() => void outbox.discard(item.id)} className={`${secondaryButton} mt-2`}>
            Discard
          </button>
        </div>
      ))}
      {me.role === "hospital_doctor" && (
        <Link to="/queue/doctor" className="block underline">
          {doctorQueue.data?.length ?? 0} waiting for doctor approval
        </Link>
      )}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">My drafts</h2>
        {drafts.isPending ? <p>Loading…</p> : <RecordList records={drafts.data ?? []} empty="No drafts." />}
      </section>
    </>
  );
}

function NsuHome() {
  const queue = useRecords({ status: "pending_nsu" });
  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-semibold">NSU review</h1>
      <Link to="/queue/nsu" className="underline">
        {queue.data?.length ?? 0} waiting for NSU approval
      </Link>
    </section>
  );
}
```

In `web/src/App.tsx`, add the import `import QueuePage from "./queues/QueuePage";` and add this line above `<Route path="*" …>`:

```tsx
      <Route path="queue/:stage" element={<QueuePage />} />
```

- [ ] **Step 5: Run everything**

Run: `cd web && npm run typecheck && npm test && npm run build && npm run e2e`
Expected: unit tests pass, the production build succeeds, and Playwright reports `8 passed`.

- [ ] **Step 6: Commit**

```bash
git add web/src web/e2e
git commit -m "feat(web): home screen, approval queues, full capture-to-approval story" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Done when

- `cd web && npm run typecheck && npm test && npm run build && npm run e2e` all pass. The e2e story covers: login → device key → study code → crop → on-device redaction (pixels checked) → upload → form validation → submit → second doctor approves → NSU returns → uploader fixes → doctor and NSU approve → Approved.
- `cd server && uv run pytest` still passes. M2 needs no server changes.
- Every Review Focus item has a passing test: Task 8 and Task 9 (number typing), Task 5 (offline, 5xx and 401 retry; no double send; refused items set aside), Task 1 (typed key; registration number variants), Task 10 (refused upload shown on home with Discard).
