import type { ReactNode } from "react";
import { Navigate } from "react-router";
import { useMe } from "../api/hooks";
import type { Me } from "../api/types";

export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.isPending) return <p className="p-6">Loading…</p>;
  if (me.isError) return <p role="alert" className="p-6 text-red-700">Cannot reach the server: {me.error.message}</p>;
  if (!me.data) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** The signed-in user. Only call inside <RequireAuth>. */
export function useCurrentUser(): Me {
  const { data } = useMe();
  if (!data) throw new Error("useCurrentUser used outside RequireAuth");
  return data;
}
