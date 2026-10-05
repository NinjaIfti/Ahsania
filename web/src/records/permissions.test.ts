import { describe, expect, it } from "vitest";
import { availableActions, canEdit, fillByHandOffered } from "./permissions";

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
  it("lets a hospital doctor release a held-back record", () => {
    expect(availableActions("hospital_doctor", "quarantined", false)).toEqual(["release"]);
    expect(availableActions("uploader", "quarantined", true)).toEqual([]);
  });
});

describe("fillByHandOffered", () => {
  const queued = "2026-10-05T10:00:00Z";
  const after = (minutes: number) => Date.parse(queued) + minutes * 60_000;

  it("waits two minutes", () => {
    expect(fillByHandOffered("uploader", "processing", queued, after(1.9))).toBe(false);
    expect(fillByHandOffered("uploader", "processing", queued, after(2))).toBe(true);
  });
  it("is only for hospital staff on a record the AI is reading", () => {
    expect(fillByHandOffered("hospital_doctor", "processing", queued, after(5))).toBe(true);
    expect(fillByHandOffered("nsu_reviewer", "processing", queued, after(5))).toBe(false);
    expect(fillByHandOffered("uploader", "draft", queued, after(5))).toBe(false);
    expect(fillByHandOffered("uploader", "processing", null, after(5))).toBe(false);
  });
});
