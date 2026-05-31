-- Project briefs: multimodal context (deck PDF + demo video + URL) → one reusable
-- brief that flows into the council as session.context. Mirrors the DDL added to
-- backend/db/migrations.sql (keep the two in sync).

create table if not exists projects (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid,                        -- app-level (JWT sub); not a FK (see orgs.owner_id)
  name        text not null,
  status      text not null default 'pending',  -- pending|extracting|ready|failed
  brief       jsonb,
  brief_text  text,
  error       text,
  created_at  timestamptz default now()
);

create table if not exists project_sources (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  kind          text not null,             -- 'pdf' | 'video' | 'url'
  filename      text,
  content_type  text,
  storage_path  text,
  content_hash  text,
  bytes         int default 0,
  extracted     jsonb,
  created_at    timestamptz default now()
);
create index if not exists project_sources_project_idx on project_sources(project_id);

alter table sessions add column if not exists project_id uuid
  references projects(id) on delete set null;

-- RLS (service key bypasses; protects any direct client access).
alter table projects        enable row level security;
alter table project_sources enable row level security;

drop policy if exists projects_owner on projects;
create policy projects_owner on projects for all to authenticated
  using (owner_id = auth.uid()) with check (owner_id = auth.uid());

drop policy if exists project_sources_owner on project_sources;
create policy project_sources_owner on project_sources for all to authenticated
  using (exists (select 1 from projects p
                 where p.id = project_sources.project_id and p.owner_id = auth.uid()))
  with check (exists (select 1 from projects p
                      where p.id = project_sources.project_id and p.owner_id = auth.uid()));
