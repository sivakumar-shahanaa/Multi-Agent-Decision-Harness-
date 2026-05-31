// TypeScript mirror of backend/schemas.py — THE FROZEN CONTRACT (ROADMAP §5-7).
// Keep in sync with the Python models.

export type EventType =
  | "position" | "thought" | "message" | "peer_request" | "peer_response"
  | "tool_call" | "tool_result" | "position_update" | "orchestrator" | "verdict"
  | "error" | "done";
// Note: project-brief extraction progress streams as a separate "extraction" SSE
// event carrying ExtractionProgress (below) — it is NOT a session EventType.

export type Stance = "YES" | "NO" | "CONDITIONAL";
export type Provider = "anthropic" | "wandb";
export type SessionStatus = "pending" | "running" | "done" | "error";
export type ProjectStatus = "pending" | "extracting" | "ready" | "failed";
export type SourceKind = "pdf" | "video" | "url";

export interface Position {
  stance: Stance; score: number; confidence: number; rationale: string;
}

export interface Agent {
  id: string; org_id: string; name: string; role: string; system_prompt: string;
  model: string; provider: Provider; weight: number; voice_id?: string | null;
  tools: string[]; position: number; structural: boolean; veto: boolean;
  created_at?: string;
}

export interface Org {
  id: string; owner_id?: string | null; name: string;
  description?: string | null; preset?: string | null; created_at?: string;
}

export interface DHEvent {
  id: string; session_id: string; seq: number; round: number;
  agent_id?: string | null; type: EventType; content: Record<string, any>;
  parent_event?: string | null; influenced_by: string[]; created_at?: string;
}

export interface Verdict {
  decision: Stance; weighted_score: number; confidence: number; summary: string;
  key_agreements: string[];
  key_conflicts: { between: string[]; issue: string }[];
  dissenting_opinions: { agent_id: string; stance: Stance; why: string }[];
  influence_ranking: { agent_id: string; influence: number }[];
}

export interface Session {
  id: string; org_id: string; question: string; context?: string | null;
  status: SessionStatus; rounds: number; final_verdict?: Verdict | null;
  weave_trace_url?: string | null; parent_session?: string | null;
  project_id?: string | null;
  weights_override?: Record<string, number> | null;
}

// ── Project brief (multimodal context) — mirrors backend/schemas.py ──
export interface Brief {
  title: string; one_liner: string; problem: string; solution: string;
  market: string; traction: string; tech: string; business_model: string;
  team: string; risks: string[]; asks: string[]; summary: string;
}

export interface ProjectSource {
  id: string; project_id: string; kind: SourceKind; filename: string;
  content_type?: string | null; storage_path?: string | null;
  content_hash?: string | null; bytes: number;
  extracted?: Record<string, any> | null; created_at?: string;
}

export interface Project {
  id: string; owner_id?: string | null; name: string; status: ProjectStatus;
  brief?: Brief | null; brief_text?: string | null; error?: string | null;
  created_at?: string;
}

export interface ProjectDetail { project: Project; sources: ProjectSource[]; }

// Streamed extraction-progress event payload (EventType "extraction").
export interface ExtractionProgress {
  stage: string; detail: string; progress: number;
}

export interface SessionDetail {
  session: Session; events: DHEvent[];
  positions: Record<string, any>[]; verdict?: Verdict | null;
}

export interface InfluenceGraph {
  nodes: { agent_id: string; name: string; weight: number; influence: number }[];
  edges: { from: string; to: string; weight: number }[];
}
