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
});

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
