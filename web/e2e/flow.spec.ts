import { fileURLToPath } from "node:url";
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

const REPORT = fileURLToPath(new URL("./fixtures/report.jpg", import.meta.url));
let studyCode = "";

test("the uploader turns a registration number into a study code and adds a cropped page", async () => {
  await login("uploader@amcgh.test");
  await page.getByRole("link", { name: "New capture" }).click();
  // start with the wrong patient and add a page, to prove a patient change drops the photos
  await page.getByLabel("Hospital registration number").fill("AMH-99999");
  await page.getByRole("button", { name: "Get study code" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /Radiology report/ }).click();
  await page.getByTestId("gallery-input").setInputFiles(REPORT);
  await page.getByRole("button", { name: "Use this page" }).click();
  await expect(page.getByRole("img", { name: "Page 1" })).toBeVisible();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByLabel("Hospital registration number").fill("AMH-00123");
  await page.getByRole("button", { name: "Get study code" }).click();
  studyCode = (await page.getByTestId("study-code").textContent()) ?? "";
  expect(studyCode).toMatch(/^AMH-[0-9A-HJKMNP-TV-Z]{10}$/);
  await expect(page.getByLabel("Hospital registration number")).toHaveCount(0);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("button", { name: /Pathology/ })).toBeDisabled();
  await page.getByRole("button", { name: /Radiology report/ }).click();
  await expect(page.getByRole("img", { name: "Page 1" })).toHaveCount(0);
  await page.getByTestId("gallery-input").setInputFiles(REPORT);
  await page.getByRole("button", { name: "Rotate right" }).click();
  await page.getByRole("button", { name: "Rotate left" }).click();
  await page.getByRole("button", { name: "Use this page" }).click();
  await expect(page.getByRole("img", { name: "Page 1" })).toBeVisible();
  await expect(page.getByText("Photo looks blurry — retake?")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Next: hide names" })).toBeEnabled();
});

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
  // The worker reads the page (PaddleOCR, then the stub model) and turns the record into a pre-filled draft.
  await page.goto(`/records/${recordId}`);
  await expect(page.getByTestId("record-status")).toHaveText("Draft", { timeout: 90_000 });
});

test("the AI fills the form; the uploader checks the amber field, fixes a mistake and submits", async () => {
  await page.goto(`/records/${recordId}`);
  await expect(page.getByRole("heading", { name: /Radiology report/ })).toBeVisible();
  await expect(page.getByRole("img", { name: "Page 1" })).toBeVisible();
  await expect(page.getByTestId("record-status")).toHaveText("Draft");
  await expect(page.getByLabel("Modality")).toHaveValue("CT");
  await expect(page.getByLabel("Study date")).toHaveValue("2026-09-01");
  await expect(page.getByLabel("Lobe")).toHaveValue("RUL");
  await expect(page.getByLabel("Long axis")).toHaveValue("2.3");
  await expect(page.locator('[data-ai="amber"]')).toHaveCount(1);
  await expect(page.locator('[data-ai="amber"]')).toContainText("Short axis");
  await expect(page.locator('[data-ai="green"]', { hasText: "Long axis" })).toBeVisible();

  // Tapping a field outlines where the AI read it.
  await page.getByLabel("Short axis").focus();
  await expect(page.getByTestId("source-box")).toBeVisible();

  // A mistake the server flags, then the fix. A changed value loses its AI marker.
  await page.getByLabel("Long axis").fill("abc");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("must be a number")).toBeVisible();
  await page.getByLabel("Long axis").fill("2.");
  await page.getByLabel("Long axis").pressSequentially("4");
  await expect(page.getByLabel("Long axis")).toHaveValue("2.4");
  await expect(page.locator("[data-ai]", { hasText: "Long axis" })).toHaveCount(0);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  await expect(page.getByText("must be a number")).toHaveCount(0);
  await page.getByRole("button", { name: "Submit for doctor review" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for doctor");
  await expect(page.getByLabel("Modality")).toBeDisabled();
  await logout();
});

async function openFromQueue(queueLink: string) {
  await page.getByRole("link", { name: queueLink }).click();
  await page.getByRole("link", { name: new RegExp(studyCode) }).click();
}

test("a second hospital doctor approves from the doctor queue", async () => {
  await login("doctor2@amcgh.test");
  await page.getByRole("link", { name: "Doctor queue" }).click();
  await expect(page.getByText("🟡 1 to check")).toBeVisible(); // the short axis is still the AI's unsure value
  await page.getByRole("link", { name: new RegExp(studyCode) }).click();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for NSU");
  await logout();
});

test("NSU returns the record with a comment and the uploader sees it on the home screen", async () => {
  await login("reviewer@nsu.test");
  await openFromQueue("NSU queue");
  await page.getByRole("button", { name: "Return…" }).click();
  await page.getByLabel("What needs fixing?").fill("Please check the short axis");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("status")).toHaveText("Returned to the uploader");
  await logout();

  await login("uploader@amcgh.test");
  await expect(page.getByText("Returned", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: new RegExp(studyCode) }).click();
  // The comment also appears in History, so match the banner's whole text to keep the locator strict.
  await expect(page.getByText(/^Returned by .+: Please check the short axis$/)).toBeVisible();
  await page.getByLabel("Short axis").fill("1.9");
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

test("an upload made while the server is unreachable waits on the device and goes up on Try now", async () => {
  await login("uploader@amcgh.test");
  await page.getByRole("link", { name: "New capture" }).click();
  await page.getByLabel("Hospital registration number").fill("AMH-77777");
  await page.getByRole("button", { name: "Get study code" }).click();
  const queuedCode = (await page.getByTestId("study-code").textContent()) ?? "";
  expect(queuedCode).toMatch(/^AMH-[0-9A-HJKMNP-TV-Z]{10}$/);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /Radiology report/ }).click();
  await page.getByTestId("gallery-input").setInputFiles(REPORT);
  await page.getByRole("button", { name: "Use this page" }).click();
  await page.getByRole("button", { name: "Next: hide names" }).click();
  await expect(page.getByText("Finding names…")).toBeHidden({ timeout: 90_000 });
  await page.getByLabel("All names and numbers are covered.").check();

  await page.route("**/api/**", (route) => route.abort());
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByText("Saved on this device — it will upload when the connection is back.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Try now" })).toBeVisible();

  await page.unroute("**/api/**");
  await page.getByRole("button", { name: "Try now" }).click();
  await expect(page.getByRole("button", { name: "Try now" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: new RegExp(queuedCode) }).first()).toBeVisible();
  await logout();
});
