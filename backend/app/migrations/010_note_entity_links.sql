-- 010_note_entity_links.sql
-- NexusEditor v2: notes 可 link 到 project / task（除咗現有 contact / company）

ALTER TABLE nexus_crm.notes
  ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES nexus_crm.projects(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS task_id UUID REFERENCES nexus_crm.tasks(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_notes_project ON nexus_crm.notes(project_id);
CREATE INDEX IF NOT EXISTS idx_notes_task ON nexus_crm.notes(task_id);
