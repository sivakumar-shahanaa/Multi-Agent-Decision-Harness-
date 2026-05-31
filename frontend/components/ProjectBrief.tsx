"use client";
// Attach a project to the council: upload a slide deck (PDF) and/or a demo video
// (MP4) and/or a website URL, watch the brief get extracted live, review + edit it,
// then attach it as context. Self-contained — the parent only needs the resulting
// project id (passed into createSession as project_id).
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type { ExtractionProgress, Project } from "../lib/types";
import { Eyebrow } from "./ui";

type Phase = "idle" | "extracting" | "review" | "failed";
const ACCEPT = ".pdf,.mp4";
const MAX_MB: Record<string, number> = { pdf: 25, mp4: 50 };

function validate(f: File): string | null {
  const isPdf = f.type === "application/pdf" || /\.pdf$/i.test(f.name);
  const isMp4 = f.type === "video/mp4" || /\.mp4$/i.test(f.name);
  if (!isPdf && !isMp4) return `${f.name}: only PDF or MP4`;
  const cap = isPdf ? MAX_MB.pdf : MAX_MB.mp4;
  if (f.size > cap * 1024 * 1024) return `${f.name}: exceeds ${cap}MB`;
  return null;
}

export function ProjectBrief({
  attachedId, onAttach, onClear, disabled,
}: {
  attachedId: string | null;
  onAttach: (projectId: string, name: string) => void;
  onClear: () => void;
  disabled?: boolean;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<ExtractionProgress | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [briefText, setBriefText] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [past, setPast] = useState<Project[]>([]);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => () => esRef.current?.close(), []);
  useEffect(() => {
    if (disabled) return;
    api.listProjects().then((p) => setPast(p.filter((x) => x.status === "ready"))).catch(() => {});
  }, [disabled, phase]);

  const finalize = useCallback(async (projectId: string) => {
    esRef.current?.close();
    try {
      const { project: p } = await api.getProject(projectId);
      setProject(p);
      setBriefText(p.brief_text ?? "");
      if (p.status === "failed") { setPhase("failed"); setError(p.error ?? "extraction failed"); }
      else setPhase("review");
    } catch (e) { setPhase("failed"); setError(String(e)); }
  }, []);

  const stream = useCallback((projectId: string) => {
    esRef.current?.close();
    const es = new EventSource(api.projectStreamUrl(projectId));
    esRef.current = es;
    es.addEventListener("extraction", (e) => {
      try {
        const { content } = JSON.parse((e as MessageEvent).data) as { content: ExtractionProgress };
        setProgress(content);
        if (content.stage === "ready" || content.stage === "failed") finalize(projectId);
      } catch { /* keepalive */ }
    });
    es.addEventListener("done", () => finalize(projectId));
    es.onerror = () => {
      // EventSource auto-reconnects on a transient drop; on a PERMANENT failure
      // (readyState CLOSED — e.g. 404 from access loss) it won't, and no terminal
      // event will arrive, so recover by re-fetching the project's real status.
      if (es.readyState === EventSource.CLOSED) finalize(projectId);
    };
  }, [finalize]);

  async function prepare() {
    setError("");
    const errs = files.map(validate).filter(Boolean) as string[];
    if (errs.length) { setError(errs[0]); return; }
    if (!files.length && !url.trim()) { setError("Attach a PDF/MP4 or a URL first."); return; }
    const form = new FormData();
    if (name.trim()) form.append("name", name.trim());
    if (url.trim()) form.append("url", url.trim());
    files.forEach((f) => form.append("files", f));
    setPhase("extracting"); setProgress({ stage: "started", detail: "Uploading…", progress: 0.02 });
    try {
      const { project_id } = await api.createProject(form);
      stream(project_id);
    } catch (e) { setPhase("failed"); setError(String(e)); }
  }

  async function attach() {
    if (!project) return;
    setSaving(true);
    try {
      if (briefText !== (project.brief_text ?? "")) await api.updateProject(project.id, { brief_text: briefText });
      onAttach(project.id, project.name);
    } catch (e) { setError(String(e)); } finally { setSaving(false); }
  }

  function reset() {
    esRef.current?.close();
    setFiles([]); setUrl(""); setName(""); setPhase("idle");
    setProgress(null); setProject(null); setBriefText(""); setError("");
  }

  async function reuse(id: string) {
    if (!id) return;
    setPhase("extracting"); setProgress({ stage: "loading", detail: "Loading saved brief…", progress: 0.5 });
    await finalize(id);
  }

  // ── attached: compact confirmation ──
  if (attachedId) {
    return (
      <div className="panel" style={{ marginTop: 14 }}>
        <div className="panel-pad row between wrapflex" style={{ gap: 10 }}>
          <span className="small" style={{ color: "var(--yes)" }}>
            ✓ Council will see the brief for <b>{project?.name ?? "your project"}</b>
          </span>
          <button className="btn btn-ghost btn-sm" onClick={() => { onClear(); reset(); }}>Change / remove</button>
        </div>
      </div>
    );
  }

  const pct = Math.round((progress?.progress ?? 0) * 100);

  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="row between wrapflex" style={{ gap: 10 }}>
          <Eyebrow>Brief the council — deck · demo · site</Eyebrow>
          {past.length > 0 && phase === "idle" && (
            <select className="mono small" defaultValue="" disabled={disabled}
              onChange={(e) => reuse(e.target.value)} style={{ maxWidth: 220 }}>
              <option value="">reuse a past project…</option>
              {past.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
        </div>

        {phase === "idle" && (
          <>
            <div className="row wrapflex" style={{ gap: 10, alignItems: "stretch" }}>
              <label className="btn btn-ghost btn-sm" style={{ cursor: "pointer" }}>
                ⬆ Attach PDF / MP4
                <input type="file" accept={ACCEPT} multiple hidden disabled={disabled}
                  onChange={(e) => { setFiles(Array.from(e.target.files ?? [])); setError(""); }} />
              </label>
              <input className="grow" placeholder="…or a website URL (https://…)" value={url}
                disabled={disabled} onChange={(e) => setUrl(e.target.value)} style={{ minWidth: 200 }} />
              <button className="btn btn-primary btn-sm" onClick={prepare}
                disabled={disabled || (!files.length && !url.trim())}>Prepare brief ▸</button>
            </div>
            {files.length > 0 && (
              <div className="row wrapflex" style={{ gap: 6 }}>
                {files.map((f, i) => (
                  <span key={i} className="mono small muted" style={{ border: "1px solid var(--line)", borderRadius: 6, padding: "2px 8px" }}>
                    {/\.pdf$/i.test(f.name) ? "📄" : "🎬"} {f.name}
                  </span>
                ))}
              </div>
            )}
            <span className="small faint">
              Extracted once into a reusable, editable brief that grounds the verdict. Optional — convene without it for an unseen question.
            </span>
          </>
        )}

        {phase === "extracting" && (
          <div className="col" style={{ gap: 8 }}>
            <div className="row" style={{ gap: 10 }}>
              <span className="dot live" />
              <span className="mono small">{progress?.detail || progress?.stage || "Working…"}</span>
              <span className="mono small faint">{pct}%</span>
            </div>
            <div style={{ height: 4, background: "var(--line)", borderRadius: 4, overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: "var(--ember)", transition: "width .4s" }} />
            </div>
          </div>
        )}

        {phase === "review" && project && (
          <div className="col" style={{ gap: 8 }}>
            <span className="small muted">Here’s what the council will see. Edit anything before you convene.</span>
            <textarea className="mono" value={briefText} onChange={(e) => setBriefText(e.target.value)}
              rows={12} style={{ width: "100%", fontSize: 12.5, lineHeight: 1.5, resize: "vertical" }} />
            <div className="row wrapflex" style={{ gap: 10 }}>
              <button className="btn btn-primary btn-sm" onClick={attach} disabled={saving}>
                {saving ? "Attaching…" : "Use this brief ▸"}
              </button>
              <button className="btn btn-ghost btn-sm" onClick={reset}>Start over</button>
            </div>
          </div>
        )}

        {phase === "failed" && (
          <div className="col" style={{ gap: 8 }}>
            <span className="small" style={{ color: "var(--no)" }}>Extraction failed — {error || "unknown error"}.</span>
            <button className="btn btn-ghost btn-sm" onClick={reset}>Try again</button>
          </div>
        )}

        {error && phase === "idle" && <span className="small" style={{ color: "var(--no)" }}>{error}</span>}
      </div>
    </div>
  );
}
