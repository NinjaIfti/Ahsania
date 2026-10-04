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
