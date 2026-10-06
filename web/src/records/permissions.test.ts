import { describe, expect, it } from "vitest";
import { availableActions, canDelete, canEdit } from "./permissions";

describe("canEdit", () => {
  it.each([
    ["doctor", "draft", true],
    ["doctor", "processing", false],
    ["doctor", "pending_admin", false],
    ["doctor", "approved", false],
    ["admin", "draft", false],
    ["admin", "pending_admin", false],
  ] as const)("%s on %s -> %s", (role, status, expected) => {
    expect(canEdit(role, status)).toBe(expected);
  });
});

describe("availableActions", () => {
  it("lets a doctor send a draft to the admin", () => {
    expect(availableActions("doctor", "draft")).toEqual(["submit"]);
  });
  it("lets a doctor stop the AI and fill the form in by hand", () => {
    expect(availableActions("doctor", "processing")).toEqual(["fill_by_hand"]);
  });
  it("lets the admin approve or send back", () => {
    expect(availableActions("admin", "pending_admin")).toEqual(["approve", "return"]);
  });
  it("lets the admin reopen an approved record", () => {
    expect(availableActions("admin", "approved")).toEqual(["reopen"]);
  });
  it("gives a doctor nothing to do while the admin decides", () => {
    expect(availableActions("doctor", "pending_admin")).toEqual([]);
  });
  it("gives the admin nothing to do on a draft", () => {
    expect(availableActions("admin", "draft")).toEqual([]);
  });
});

describe("canDelete", () => {
  const mine = { created_by_id: 1, sent_to_admin: false };
  it.each([
    ["processing", true],
    ["draft", true],
    ["pending_admin", false],
    ["approved", false],
  ] as const)("my unsent %s -> %s", (status, expected) => {
    expect(canDelete({ id: 1, role: "doctor" }, { ...mine, status })).toBe(expected);
  });
  it("refuses a draft the admin sent back", () => {
    expect(canDelete({ id: 1, role: "doctor" }, { ...mine, status: "draft", sent_to_admin: true })).toBe(false);
  });
  it("refuses another doctor's draft and the admin", () => {
    expect(canDelete({ id: 2, role: "doctor" }, { ...mine, status: "draft" })).toBe(false);
    expect(canDelete({ id: 1, role: "admin" }, { ...mine, status: "draft" })).toBe(false);
  });
});
