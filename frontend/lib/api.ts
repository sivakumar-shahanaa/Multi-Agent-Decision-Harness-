// Typed client for the Decision Harness API (ROADMAP §6).
import type { Agent, InfluenceGraph, Org, SessionDetail } from "./types";

export interface CreateSessionResponse { session_id: string }

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// The current Supabase access token, kept in sync by AuthProvider (lib/auth.tsx)
// on every sign-in / token refresh. Read synchronously by both j() and streamUrl().
let accessToken: string | null = null;
export function setAccessToken(token: string | null): void {
  accessToken = token;
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  health: () => j<{ ok: boolean; repo: string }>("/health"),
  // Idempotent first-login bootstrap: seeds the Judge Panel if the user has none,
  // and returns all their orgs.
  ensureSeed: () => j<Org[]>("/orgs/ensure-seed", { method: "POST" }),
  listOrgs: () => j<Org[]>("/orgs"),
  listAgents: (orgId: string) => j<Agent[]>(`/orgs/${orgId}/agents`),
  createSession: (body: { org_id: string; question: string; context?: string; rounds?: number }) =>
    j<CreateSessionResponse>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  getSession: (id: string) => j<SessionDetail>(`/sessions/${id}`),
  rerun: (id: string, body: { weights_override?: Record<string, number>; context?: string }) =>
    j<CreateSessionResponse>(`/sessions/${id}/rerun`, { method: "POST", body: JSON.stringify(body) }),
  influence: (id: string) => j<InfluenceGraph>(`/sessions/${id}/influence`),
  // EventSource can't set headers, so the token rides along as a query param;
  // the backend verifies it the same way (get_current_user_sse).
  streamUrl: (id: string) => {
    const base = `${API_URL}/sessions/${id}/stream`;
    return accessToken ? `${base}?access_token=${encodeURIComponent(accessToken)}` : base;
  },
};
