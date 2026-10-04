import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "./client";
import type { Me, RecordDetail, RecordSummary, TemplateOut } from "./types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

export function useTemplates() {
  return useQuery({ queryKey: ["templates"], queryFn: () => api<TemplateOut[]>("/templates"), staleTime: 300_000 });
}

export function useRecord(id: string) {
  return useQuery({
    queryKey: ["record", id],
    queryFn: () => api<RecordDetail>(`/records/${id}`),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 3000 : false),
  });
}

export interface RecordFilter {
  status?: string;
  mine?: boolean;
  study_code?: string;
}

export function useRecords(filter: RecordFilter, enabled = true) {
  const params = new URLSearchParams();
  if (filter.status) params.set("status", filter.status);
  if (filter.mine) params.set("mine", "true");
  if (filter.study_code) params.set("study_code", filter.study_code);
  return useQuery({
    queryKey: ["records", filter],
    queryFn: () => api<RecordSummary[]>(`/records?${params}`),
    enabled,
  });
}

export function useExpectedFingerprint(enabled: boolean) {
  return useQuery({
    queryKey: ["fingerprint"],
    queryFn: () => api<{ expected: string | null }>("/device/fingerprint"),
    enabled,
  });
}
