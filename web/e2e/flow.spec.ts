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
