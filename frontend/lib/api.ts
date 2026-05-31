// Typed client for the Decision Harness API (ROADMAP §6).
import type { Agent, InfluenceGraph, Org, Project, ProjectDetail, SessionDetail } from "./types";

export interface CreateSessionResponse { session_id: string }
export interface CreateProjectResponse { project_id: string }

// Mirrors backend AgentCreate / AgentUpdate (schemas.py §6).
export interface AgentCreateBody {
  name: string; role: string; system_prompt: string;
  model?: string; provider?: "anthropic" | "wandb"; weight?: number;
  voice_id?: string | null; tools?: string[]; position?: number;
}
export type AgentUpdateBody = Partial<AgentCreateBody>;

// Default to the literal IPv4 loopback, NOT "localhost". On macOS `localhost`
// resolves to both 127.0.0.1 and ::1, and browsers may pick IPv6 ::1 first —
// but uvicorn binds IPv4-only by default, so a ::1 connection is refused and
// fetch throws "TypeError: Failed to fetch". 127.0.0.1 is unambiguously IPv4.
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

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

// Multipart POST: set ONLY Authorization. The browser sets the multipart
// Content-Type + boundary itself — setting it manually drops the boundary.
async function postForm<T>(path: string, form: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  const res = await fetch(`${API_URL}${path}`, { method: "POST", headers, body: form });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  health: () => j<{ ok: boolean; repo: string }>("/health"),
  // Idempotent first-login bootstrap: seeds the Judge Panel if the user has none,
  // and returns all their orgs.
  ensureSeed: () => j<Org[]>("/orgs/ensure-seed", { method: "POST" }),
  listOrgs: () => j<Org[]>("/orgs"),
  createOrg: (body: { name: string; description?: string; preset?: string }) =>
    j<Org>("/orgs", { method: "POST", body: JSON.stringify(body) }),
  // AI org-builder (ROADMAP §9.4): synthesize a full panel from a prompt.
  generateOrg: (prompt: string) =>
    j<Org>("/orgs/generate", { method: "POST", body: JSON.stringify({ prompt }) }),
  listAgents: (orgId: string) => j<Agent[]>(`/orgs/${orgId}/agents`),
  createAgent: (orgId: string, body: AgentCreateBody) =>
    j<Agent>(`/orgs/${orgId}/agents`, { method: "POST", body: JSON.stringify(body) }),
  updateAgent: (agentId: string, body: AgentUpdateBody) =>
    j<Agent>(`/agents/${agentId}`, { method: "PATCH", body: JSON.stringify(body) }),
  createSession: (body: { org_id: string; question: string; context?: string; rounds?: number; project_id?: string }) =>
    j<CreateSessionResponse>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  getSession: (id: string) => j<SessionDetail>(`/sessions/${id}`),

  // ── Project briefs (deck + demo video + URL → reusable context) ──
  createProject: (form: FormData) =>
    postForm<CreateProjectResponse>("/projects", form),
  listProjects: () => j<Project[]>("/projects"),
  getProject: (id: string) => j<ProjectDetail>(`/projects/${id}`),
  updateProject: (id: string, body: { name?: string; brief_text?: string }) =>
    j<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  projectStreamUrl: (id: string) => {
    const base = `${API_URL}/projects/${id}/stream`;
    return accessToken ? `${base}?access_token=${encodeURIComponent(accessToken)}` : base;
  },
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
