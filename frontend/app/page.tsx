"use client";
// Boardroom-lite (Hour 0). WS-C grows this into the full Boardroom + Inspector +
// InfluenceGraph + VerdictPanel (ROADMAP §6 frontend). Proves the end-to-end flow:
// pick org -> ask -> live debate streams in -> verdict appears.
import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useEventStream } from "../lib/useEventStream";
import type { Agent, Org, Verdict } from "../lib/types";

export default function Home() {
  const [health, setHealth] = useState<string>("…");
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgId, setOrgId] = useState<string>("");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [question, setQuestion] = useState(
    "Should this project win Most Sophisticated Harness?");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const { events, done } = useEventStream(sessionId);
  const { user, signOut } = useAuth();

  useEffect(() => {
    api.health().then((h) => setHealth(`ok · ${h.repo}`)).catch((e) => setHealth(String(e)));
    // Seeds the Judge Panel on first login (idempotent), then returns the user's orgs.
    api.ensureSeed().then((o) => { setOrgs(o); if (o[0]) setOrgId(o[0].id); })
      .catch((e) => setHealth(String(e)));
  }, []);
  useEffect(() => { if (orgId) api.listAgents(orgId).then(setAgents); }, [orgId]);

  const agentById = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a])), [agents]);

  // latest message per agent
  const latest: Record<string, string> = {};
  const stance: Record<string, { stance: string; score: number }> = {};
  let verdict: Verdict | null = null;
  for (const e of events) {
    if (e.type === "message" && e.agent_id) latest[e.agent_id] = e.content.text;
    if ((e.type === "position" || e.type === "position_update") && e.agent_id)
      stance[e.agent_id] = { stance: e.content.stance, score: e.content.score };
    if (e.type === "verdict") verdict = e.content as Verdict;
  }

  async function run() {
    setSessionId(null);
    const { session_id } = await api.createSession({ org_id: orgId, question, rounds: 3 });
    setSessionId(session_id);
  }

  return (
    <div className="wrap">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <h1>Decision Harness</h1>
        {user && (
          <div className="muted small">
            {user.email} ·{" "}
            <a href="#" onClick={(e) => { e.preventDefault(); signOut(); }}>sign out</a>
          </div>
        )}
      </div>
      <div className="muted small">backend: {health}</div>

      <div className="panel" style={{ margin: "16px 0" }}>
        <div className="row">
          <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <input style={{ flex: 1, minWidth: 280 }} value={question}
                 onChange={(e) => setQuestion(e.target.value)} />
          <button onClick={run} disabled={!orgId}>Run debate</button>
        </div>
        <div className="muted small" style={{ marginTop: 8 }}>
          {agents.length} agents · {sessionId ? (done ? "debate complete" : "debating…") : "idle"}
        </div>
      </div>

      <div className="grid">
        {/* Boardroom: one seat per agent with latest stance + message */}
        <div className="panel">
          <b>Boardroom</b>
          {agents.map((a) => (
            <div className="seat" key={a.id}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <b>{a.name}</b>
                {stance[a.id] && (
                  <span className={`badge ${stance[a.id].stance}`}>
                    {stance[a.id].stance} {stance[a.id].score}/10
                  </span>
                )}
              </div>
              <div className="muted small">{a.role}</div>
              <div className="small" style={{ marginTop: 6 }}>{latest[a.id] ?? "…"}</div>
            </div>
          ))}
        </div>

        {/* Transcript: the inspectable event stream */}
        <div className="panel" style={{ maxHeight: 520, overflow: "auto" }}>
          <b>Transcript ({events.length})</b>
          {events.map((e) => (
            <div className="bubble small" key={e.id}>
              <span className="muted">r{e.round} · {e.type}{e.agent_id ? ` · ${agentById[e.agent_id]?.name ?? ""}` : ""}</span>
              <div>{e.content.text ?? e.content.action ?? JSON.stringify(e.content).slice(0, 160)}</div>
            </div>
          ))}
        </div>
      </div>

      {verdict && (
        <div className="panel" style={{ marginTop: 16 }}>
          <b>Verdict</b>
          <div className="row" style={{ marginTop: 8 }}>
            <span className={`badge ${verdict.decision}`}>{verdict.decision}</span>
            <span>weighted <b>{verdict.weighted_score}</b>/10</span>
            <span className="muted">confidence {verdict.confidence}</span>
          </div>
          <div className="small" style={{ marginTop: 8 }}>{verdict.summary}</div>
        </div>
      )}
    </div>
  );
}
