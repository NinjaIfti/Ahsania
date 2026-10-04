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
