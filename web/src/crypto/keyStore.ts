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
