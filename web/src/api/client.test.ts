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
