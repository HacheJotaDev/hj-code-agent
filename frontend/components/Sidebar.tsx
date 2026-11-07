"use client";

/** Barra lateral: proyectos, conversaciones, nueva conversación, tema y salida. */
import { useState } from "react";
import type { Conversation, Project } from "@/lib/types";
import { api } from "@/lib/api";
import { ICONS, Icon, ThemeToggle } from "./ui";

export default function Sidebar({
  projects,
  conversations,
  activeProjectId,
  activeConvId,
  onSelectProject,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onCreateProject,
  onImportProject,
  onLogout,
  onClose,
}: {
  projects: Project[];
  conversations: Conversation[];
  activeProjectId: number | null;
  activeConvId: number | null;
  onSelectProject: (id: number) => void;
  onSelectConversation: (id: number) => void;
  onNewConversation: () => void;
  onDeleteConversation: (id: number) => void;
  onCreateProject: (name: string) => Promise<void>;
  onImportProject: (name: string, file: File) => Promise<void>;
  onLogout: () => void;
  onClose?: () => void;
}) {
  const [showNewProject, setShowNewProject] = useState(false);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);

  async function createProject() {
    if (!newName.trim()) return;
    setBusy(true);
    try {
      await onCreateProject(newName.trim());
      setNewName("");
      setShowNewProject(false);
    } finally {
      setBusy(false);
    }
  }

  async function importProject(file: File) {
    if (!newName.trim()) return;
    setBusy(true);
    try {
      await onImportProject(newName.trim(), file);
      setShowNewProject(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside
      className="h-full w-72 flex flex-col border-r"
      style={{ background: "var(--bg-sidebar)", borderColor: "var(--border)" }}
    >
      <div className="flex items-center gap-2 px-3 py-3 border-b" style={{ borderColor: "var(--border)" }}>
        <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-sm font-bold" style={{ background: "var(--accent)" }}>
          HJ
        </div>
        <span className="font-semibold text-sm flex-1">HacheCode Agent</span>
        {onClose && (
          <button className="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 md:hidden" onClick={onClose} aria-label="Cerrar menú">
            <Icon path={ICONS.close} />
          </button>
        )}
      </div>

      <div className="p-3">
        <button
          onClick={onNewConversation}
          className="w-full flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium text-white"
          style={{ background: "var(--accent)" }}
        >
          <Icon path={ICONS.plus} size={16} /> Nueva conversación
        </button>
      </div>

      <div className="px-3">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-dim)" }}>
            Proyectos
          </span>
          <button
            className="p-1 rounded hover:bg-black/5 dark:hover:bg-white/10"
            onClick={() => setShowNewProject((v) => !v)}
            title="Nuevo proyecto"
            aria-label="Nuevo proyecto"
          >
            <Icon path={ICONS.plus} size={14} />
          </button>
        </div>
        {showNewProject && (
          <div className="mb-2 rounded-lg border p-2 flex flex-col gap-2" style={{ borderColor: "var(--border)" }}>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Nombre del proyecto"
              className="rounded-md border px-2 py-1.5 text-sm bg-transparent"
              style={{ borderColor: "var(--border)" }}
            />
            <div className="flex gap-2">
              <button
                onClick={createProject}
                disabled={busy || !newName.trim()}
                className="flex-1 rounded-md py-1.5 text-xs font-medium text-white disabled:opacity-40"
                style={{ background: "var(--accent)" }}
              >
                Crear
              </button>
              <label
                className={`flex-1 rounded-md py-1.5 text-xs font-medium text-center border cursor-pointer ${busy ? "opacity-40" : ""}`}
                style={{ borderColor: "var(--border)" }}
              >
                Importar ZIP
                <input
                  type="file"
                  accept=".zip,.tar.gz,.tgz,.tar"
                  className="hidden"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void importProject(f);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
          </div>
        )}
        <ul className="mb-3 max-h-40 overflow-y-auto">
          {projects.map((p) => (
            <li key={p.id}>
              <button
                onClick={() => onSelectProject(p.id)}
                className={`w-full text-left px-2 py-1.5 rounded-lg text-sm truncate flex items-center gap-2 ${
                  p.id === activeProjectId ? "font-semibold" : ""
                }`}
                style={
                  p.id === activeProjectId
                    ? { background: "var(--accent-soft)", color: "var(--accent)" }
                    : undefined
                }
              >
                <Icon path={ICONS.folder} size={14} />
                {p.name}
              </button>
            </li>
          ))}
          {projects.length === 0 && (
            <li className="text-xs px-2 py-1" style={{ color: "var(--text-dim)" }}>
              Sin proyectos todavía
            </li>
          )}
        </ul>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-dim)" }}>
          Conversaciones
        </span>
        <ul className="mt-1.5">
          {conversations.map((c) => (
            <li key={c.id} className="group flex items-center">
              <button
                onClick={() => onSelectConversation(c.id)}
                className={`flex-1 text-left px-2 py-1.5 rounded-lg text-sm truncate ${
                  c.id === activeConvId ? "font-semibold" : ""
                }`}
                style={
                  c.id === activeConvId
                    ? { background: "var(--accent-soft)", color: "var(--accent)" }
                    : undefined
                }
                title={c.title || `Conversación #${c.id}`}
              >
                {c.title || `Conversación #${c.id}`}
              </button>
              <button
                onClick={() => onDeleteConversation(c.id)}
                className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-black/5 dark:hover:bg-white/10"
                title="Eliminar conversación"
                aria-label="Eliminar conversación"
              >
                <Icon path={ICONS.trash} size={13} />
              </button>
            </li>
          ))}
          {conversations.length === 0 && (
            <li className="text-xs px-2 py-1" style={{ color: "var(--text-dim)" }}>
              Empieza una conversación nueva
            </li>
          )}
        </ul>
      </div>

      <div className="flex items-center justify-between px-3 py-3 border-t" style={{ borderColor: "var(--border)" }}>
        <ThemeToggle />
        <button
          onClick={onLogout}
          className="p-2 rounded-lg hover:bg-black/5 dark:hover:bg-white/10"
          title="Cerrar sesión"
          aria-label="Cerrar sesión"
        >
          <Icon path={ICONS.logout} />
        </button>
      </div>
    </aside>
  );
}
