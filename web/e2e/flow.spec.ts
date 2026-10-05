import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "demo-pass-123";
const DOCTOR_PASSWORD = "dr-test-pass-1";
const REPORT = fileURLToPath(new URL("./fixtures/report.jpg", import.meta.url));

test.describe.configure({ mode: "serial" });

let page: Page;
test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});
test.afterAll(async () => {
  await page.close();
});

async function login(username: string, password = PASSWORD) {
  await page.goto("/login");
  await page.getByLabel("ID").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
}

async function logout() {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

/** Form, one cropped page, then the patient ID (typed over whatever was read off the photo); stops with both upload buttons ready. */
async function capture(patientId: string) {
  await page.getByRole("link", { name: "New capture" }).click();
  await expect(page.getByRole("button", { name: /Pathology/ })).toBeDisabled();
  await page.getByRole("button", { name: /Radiology report/ }).click();
  await page.getByTestId("gallery-input").setInputFiles(REPORT);
  await page.getByRole("button", { name: "Rotate right" }).click();
  await page.getByRole("button", { name: "Rotate left" }).click();
  await page.getByRole("button", { name: "Use this page" }).click();
  await expect(page.getByRole("img", { name: "Page 1" })).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Reading the patient ID from the photos…")).toHaveCount(0, { timeout: 60_000 });
  await page.getByLabel("Patient ID (RC…)").fill(patientId);
  await expect(page.getByRole("button", { name: "Let the AI fill it" })).toBeEnabled();
}

async function openRecord(patientId: string) {
  await page.getByRole("link", { name: new RegExp(patientId) }).first().click();
}

test("a wrong password is refused; the admin signs in and out", async () => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("ID").fill("admin");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Invalid ID or password");
  await login("admin");
  await expect(page.getByText("Demo Admin · Admin")).toBeVisible();
  await logout();
});

test("the admin creates a doctor account", async () => {
  await login("admin");
  await page.getByRole("link", { name: "Accounts" }).click();
  await page.getByLabel("Name").fill("Dr. Test");
  await page.getByLabel("ID").fill("dr.test");
  await page.getByLabel("Password").fill(DOCTOR_PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("cell", { name: "dr.test" })).toBeVisible();
  await logout();
});

let aiRecord = "";
let handRecord = "";

test("the doctor refuses a malformed patient ID, then the AI fills the form", async () => {
  await login("dr.test", DOCTOR_PASSWORD);
  await expect(page.getByText("Dr. Test · Doctor")).toBeVisible();
  await capture("12345");
  await page.getByRole("button", { name: "Let the AI fill it" }).click();
  await expect(page.getByRole("alert")).toHaveText("Patient ID must be RC followed by numbers");
  await page.getByLabel("Patient ID (RC…)").fill("rc 555");
  await page.getByRole("button", { name: "Let the AI fill it" }).click();
  await expect(page).toHaveURL(/\/records\/[0-9a-f-]{36}$/);
  aiRecord = page.url().split("/").pop()!;
  await expect(page.getByText("Patient ID RC555")).toBeVisible();
  // The worker reads the page (PaddleOCR, then the stub model) and turns the record into a pre-filled draft.
  await expect(page.getByTestId("record-status")).toHaveText("Draft", { timeout: 90_000 });

  await expect(page.getByLabel("Modality")).toHaveValue("CT");
  await expect(page.getByLabel("Study date")).toHaveValue("2026-09-01");
  await expect(page.getByLabel("Lobe")).toHaveValue("RUL");
  await expect(page.locator('[data-ai="amber"]')).toHaveCount(1);
  await expect(page.locator('[data-ai="amber"]')).toContainText("Short axis");
  // Tapping a field outlines where the AI read it.
  await page.getByLabel("Short axis").focus();
  await expect(page.getByTestId("source-box")).toBeVisible();
  // A mistake the server flags, then the fix.
  await page.getByLabel("Long axis").fill("abc");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("must be a number")).toBeVisible();
  await page.getByLabel("Long axis").fill("2.");
  await page.getByLabel("Long axis").pressSequentially("4");
  await expect(page.getByLabel("Long axis")).toHaveValue("2.4");
  await page.getByRole("button", { name: "Approve and send to admin" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for admin");
  await expect(page.getByLabel("Modality")).toBeDisabled();
});

test("the doctor fills a second record by hand without waiting for the AI", async () => {
  await page.goto("/");
  await capture("RC777");
  await page.getByRole("button", { name: "I'll fill it myself" }).click();
  await expect(page).toHaveURL(/\/records\/[0-9a-f-]{36}$/);
  handRecord = page.url().split("/").pop()!;
  await expect(page.getByTestId("record-status")).toHaveText("Draft");
  await expect(page.getByLabel("Modality")).toHaveValue("");
  await page.getByLabel("Modality").selectOption("MRI");
  await page.getByLabel("Study date").fill("2026-08-15");
  await page.getByRole("button", { name: "Approve and send to admin" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for admin");
  await logout();
});

test("the admin sends the AI record back; the doctor fixes it and approves again", async () => {
  await login("admin");
  await expect(page.getByRole("heading", { name: "Waiting for admin" })).toBeVisible();
  await openRecord("RC555");
  await page.getByRole("button", { name: "Send back…" }).click();
  await page.getByLabel("What needs fixing?").fill("Please check the short axis");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("status")).toHaveText("Sent back to the doctor");
  await logout();

  await login("dr.test", DOCTOR_PASSWORD);
  const sentBack = page.locator("section", { has: page.getByRole("heading", { name: "Sent back to me" }) });
  await expect(sentBack.getByText("RC555")).toBeVisible();
  await openRecord("RC555");
  // The comment also appears in History, so match the banner's whole text to keep the locator strict.
  await expect(page.getByText(/^Sent back by .+: Please check the short axis$/)).toBeVisible();
  await page.getByLabel("Short axis").fill("1.9");
  await page.getByRole("button", { name: "Approve and send to admin" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for admin");
  await logout();
});

test("the admin approves both records", async () => {
  await login("admin");
  for (const id of [aiRecord, handRecord]) {
    await page.goto(`/records/${id}`);
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByTestId("record-status")).toHaveText("Approved");
  }
  await page.getByRole("link", { name: "All records" }).click();
  await page.getByLabel("Show").selectOption("approved");
  await expect(page.getByRole("link", { name: /RC555/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /RC777/ })).toBeVisible();
  await logout();
});

test("an upload made while the server is unreachable waits on the device and goes up on Try now", async () => {
  await login("dr.test", DOCTOR_PASSWORD);
  await capture("RC888");
  await page.route("**/api/**", (route) => route.abort());
  await page.getByRole("button", { name: "I'll fill it myself" }).click();
  await expect(page.getByText("Saved on this device — it will upload when the connection is back.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Try now" })).toBeVisible();

  await page.unroute("**/api/**");
  await page.getByRole("button", { name: "Try now" }).click();
  await expect(page.getByRole("button", { name: "Try now" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /RC888/ }).first()).toBeVisible();
  await logout();
});
