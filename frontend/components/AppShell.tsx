"use client";

/** Orquestador principal del panel web V4.
 *
 * - Sidebar (proyectos + conversaciones) · chat central · panel derecho con
 *   Tareas / Archivos / Git.
 * - Tareas en vivo por SSE con reconexión automática (Last-Event-ID).
 * - Al volver a abrir la conversación se recupera la tarea en marcha y todo
 *   el historial de eventos desde la BD (persistencia real).
 * - Móvil: sidebar en cajón, panel derecho a pantalla completa, composer fijo.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type {
  ChatMessage, Conversation, Me, ModelsResponse, Project, Task,
  TaskEvent, UsageSummary,
} from "@/lib/types";
import { api, getCsrf, setCsrf } from "@/lib/api";
import { useTaskStream } from "@/lib/useTaskStream";
import Sidebar from "./Sidebar";
import MessageView from "./MessageView";
import Composer from "./Composer";
import TaskPanel, { type TaskActivity } from "./TaskPanel";
import FilesPanel from "./FilesPanel";
import GitPanel from "./GitPanel";
import { ICONS, Icon, Spinner } from "./ui";

const EMPTY_ACTIVITY: TaskActivity = {
  taskId: 0, status: "queued", plan: [], tools: [], notifs: [],
  summary: null, error: null, steps: null, cost: null,
  filesTouched: [], commandsCount: null, testsCount: null,
  planIncompleteNote: null, zipAvailable: false,
};

export default function AppShell() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [convId, setConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [modelsKey, setModelsKey] = useState(0);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [activity, setActivity] = useState<TaskActivity | null>(null);
  const [streamTaskId, setStreamTaskId] = useState<number | null>(null);
  const [panel, setPanel] = useState<"tareas" | "archivos" | "git">("tareas");
  const [panelOpen, setPanelOpen] = useState(false); // móvil: cerrado; escritorio: se abre abajo
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [filesKey, setFilesKey] = useState(0);
  const [globalError, setGlobalError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // --------------------------- carga inicial ----------------------------
  const refreshConvs = useCallback(async () => {
    const r = await api.get<{ conversations: Conversation[] }>("/conversations?limit=50");
    setConvs(r.conversations);
  }, []);

  const refreshUsage = useCallback(async () => {
    try {
      setUsage(await api.get<UsageSummary>("/usage/summary"));
    } catch { /* no bloquea */ }
  }, []);

  const refreshModels = useCallback(async () => {
    try {
      setModels(await api.get<ModelsResponse>("/models"));
    } catch { /* se reintentara */ }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const meData = await api.get<Me>("/auth/me");
        setMe(meData);
        setCsrf(meData.csrf_token);
        const [pr, cv] = await Promise.all([
          api.get<{ projects: Project[] }>("/projects"),
          api.get<{ conversations: Conversation[] }>("/conversations?limit=50"),
        ]);
        setProjects(pr.projects);
        setConvs(cv.conversations);
        // auto-seleccionar el primer proyecto (experiencia: llegar y escribir)
        if (pr.projects.length > 0) setProjectId(pr.projects[0].id);
        void refreshModels();
        void refreshUsage();
      } catch (e) {
        setGlobalError(e instanceof Error ? e.message : String(e));
      } finally {
        setReady(true);
      }
    })();
  }, [refreshModels, refreshUsage]);

  useEffect(() => {
    // En escritorio el panel derecho nace abierto; en móvil solo a demanda
    if (typeof window !== "undefined" && window.matchMedia("(min-width: 1280px)").matches) {
      setPanelOpen(true);
    }
  }, []);

  // ------------------------- mensajes + tareas ---------------------------
  const loadMessages = useCallback(async (cid: number) => {
    const r = await api.get<{ messages: ChatMessage[] }>(`/conversations/${cid}/messages`);
    setMessages(r.messages);
  }, []);

  /** Restaura una tarea existente (en marcha o terminada) al abrir una conversación. */
  const restoreTask = useCallback(async (tid: number) => {
    const t = await api.get<Task>(`/tasks/${tid}`);
    setActivity({
      taskId: t.id, status: t.status, plan: t.plan || [], tools: [], notifs: [],
      summary: t.status === "done" ? resumenDe(t.result) : null,
      error: t.error, steps: t.steps, cost: null,
      filesTouched: [], commandsCount: null, testsCount: null,
      planIncompleteNote: null, zipAvailable: !!t.zip_available,
    });
    if (t.status === "queued" || t.status === "running") {
      setStreamTaskId(t.id);
    }
    // eventos históricos (evidencia completa aunque la tarea ya terminó)
    const evs = await api.get<{ events: TaskEvent[] }>(`/tasks/${tid}/events?after=0`);
    let acc = EMPTY_ACTIVITY;
    for (const ev of evs.events) acc = applyEvent(acc, ev, true);
    setActivity((prev) => ({
      ...(prev && prev.taskId === tid ? prev : acc),
      taskId: tid, status: t.status,
      plan: (acc.plan.length ? acc.plan : t.plan || []),
      summary: acc.summary ?? (t.status === "done" ? resumenDe(t.result) : null),
      error: acc.error ?? t.error,
      steps: acc.steps ?? t.steps,
      zipAvailable: !!t.zip_available,
      tools: acc.tools, notifs: acc.notifs,
      filesTouched: acc.filesTouched, commandsCount: acc.commandsCount,
      testsCount: acc.testsCount, planIncompleteNote: acc.planIncompleteNote,
    }));
  }, []);

  const selectConversation = useCallback(async (cid: number) => {
    setConvId(cid);
    setSidebarOpen(false);
    setStreamTaskId(null);
    setActivity(null);
    await loadMessages(cid);
    // ¿hay una tarea viva o reciente en esta conversación?
    try {
      const r = await api.get<{ tasks: Task[] }>(`/tasks?conversation_id=${cid}&limit=10`);
      const live = r.tasks.find((t) => t.status === "queued" || t.status === "running");
      const latest = r.tasks[0];
      if (live) await restoreTask(live.id);
      else if (latest) await restoreTask(latest.id);
    } catch { /* sin tareas */ }
  }, [loadMessages, restoreTask]);

  // ------------------------------- SSE -----------------------------------
  const handleEvent = useCallback((ev: TaskEvent) => {
    setActivity((prev) => {
      if (!prev) return prev;
      const next = applyEvent(prev, ev, false);
      return next;
    });
    if (ev.type === "status") {
      const status = String((ev.data as { status?: string }).status || "");
      if (["done", "failed", "cancelled", "interrupted"].includes(status)) {
        // refrescar chat, archivos, uso y lista de conversaciones
        if (convId) void loadMessages(convId);
        setFilesKey((k) => k + 1);
        void refreshUsage();
        void refreshConvs();
        void refreshModels();
        setTimeout(() => setStreamTaskId(null), 300);
      }
    }
  }, [convId, loadMessages, refreshConvs, refreshModels, refreshUsage]);

  useTaskStream(streamTaskId, handleEvent);

  // ------------------------------ acciones --------------------------------
  async function newConversation() {
    try {
      const r = await api.post<{ conversation: Conversation }>("/conversations", {
        project_id: projectId,
      });
      setConvs((c) => [r.conversation, ...c]);
      setConvId(r.conversation.id);
      setMessages([]);
      setActivity(null);
      setStreamTaskId(null);
      setSidebarOpen(false);
    } catch (e) {
      setGlobalError(e instanceof Error ? e.message : String(e));
    }
  }

  async function createProject(name: string) {
    const r = await api.post<{ project: Project }>("/projects", { name });
    setProjects((p) => [r.project, ...p]);
    setProjectId(r.project.id);
  }

  async function importProject(name: string, file: File) {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("file", file);
    const res = await fetch(api.downloadUrl("/projects/import"), {
      method: "POST", body: fd, credentials: "same-origin",
      headers: { "X-CSRF-Token": csrfHeader() },
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Error ${res.status}`);
    }
    const r = await res.json() as { project: Project };
    setProjects((p) => [r.project, ...p]);
    setProjectId(r.project.id);
  }

  async function sendMessage(text: string) {
    let cid = convId;
    if (!cid) {
      cid = await newConversationAndGet();
      if (!cid) return;
    }
    // mensaje optimista del usuario
    setMessages((m) => [...m, {
      id: -Date.now(), role: "user", content: text,
    }]);
    try {
      const r = await api.post<{ task_id: number }>(`/conversations/${cid}/messages`, { text });
      setActivity({ ...EMPTY_ACTIVITY, taskId: r.task_id, status: "queued" });
      setStreamTaskId(r.task_id);
      setPanel("tareas");
      setPanelOpen(true);
      await loadMessages(cid);
      void refreshConvs();
    } catch (e) {
      setGlobalError(e instanceof Error ? e.message : String(e));
      await loadMessages(cid);
    }
  }

  async function newConversationAndGet(): Promise<number | null> {
    try {
      const r = await api.post<{ conversation: Conversation }>("/conversations", {
        project_id: projectId,
      });
      setConvs((c) => [r.conversation, ...c]);
      setConvId(r.conversation.id);
      return r.conversation.id;
    } catch (e) {
      setGlobalError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }

  async function stopTask() {
    if (!activity) return;
    try {
      await api.post(`/tasks/${activity.taskId}/cancel`);
    } catch (e) {
      setGlobalError(e instanceof Error ? e.message : String(e));
    }
  }

  async function retryTask(tid: number) {
    try {
      const r = await api.post<{ task_id: number }>(`/tasks/${tid}/retry`);
      setActivity({ ...EMPTY_ACTIVITY, taskId: r.task_id, status: "queued" });
      setStreamTaskId(r.task_id);
    } catch (e) {
      setGlobalError(e instanceof Error ? e.message : String(e));
    }
  }

  async function attachZip(file: File) {
    if (!projectId) {
      setGlobalError("Selecciona un proyecto primero");
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(api.downloadUrl(`/projects/${projectId}/upload`), {
        method: "POST", body: fd, credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfHeader() },
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Error ${res.status}`);
      }
      setFilesKey((k) => k + 1);
      setGlobalError("");
    } catch (e) {
      setGlobalError(e instanceof Error ? e.message : String(e));
    }
  }

  async function logout() {
    try {
      await api.post("/auth/logout");
    } finally {
      setCsrf(null);
      router.replace("/login");
    }
  }

  function downloadZip(tid: number) {
    window.open(api.downloadUrl(`/tasks/${tid}/zip`), "_blank");
  }

  // ------------------------------ render ----------------------------------
  const activeProject = projects.find((p) => p.id === projectId) || null;
  const running = streamTaskId !== null;
  const disabledReason = !projectId
    ? "Selecciona o crea un proyecto en la barra lateral para empezar."
    : null;

  if (!ready) {
    return (
      <main className="min-h-dvh flex items-center justify-center gap-2 text-sm" style={{ color: "var(--text-dim)" }}>
        <Spinner size={18} /> Conectando con el backend…
      </main>
    );
  }

  return (
    <div className="h-dvh flex overflow-hidden">
      {/* Sidebar: estática en >=md, cajón en móvil */}
      <div className="hidden md:block h-full">
        <Sidebar
          projects={projects} conversations={convs}
          activeProjectId={projectId} activeConvId={convId}
          onSelectProject={(id) => { setProjectId(id); setFilesKey((k) => k + 1); }}
          onSelectConversation={(id) => void selectConversation(id)}
          onNewConversation={() => void newConversation()}
          onDeleteConversation={async (id) => {
            if (!confirm("¿Eliminar esta conversación?")) return;
            await api.del(`/conversations/${id}`);
            if (convId === id) { setConvId(null); setMessages([]); }
            void refreshConvs();
          }}
          onCreateProject={createProject}
          onImportProject={importProject}
          onLogout={() => void logout()}
        />
      </div>
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setSidebarOpen(false)} />
          <div className="absolute left-0 top-0 h-full shadow-2xl">
            <Sidebar
              projects={projects} conversations={convs}
              activeProjectId={projectId} activeConvId={convId}
              onSelectProject={(id) => { setProjectId(id); setFilesKey((k) => k + 1); }}
              onSelectConversation={(id) => void selectConversation(id)}
              onNewConversation={() => void newConversation()}
              onDeleteConversation={async (id) => {
                if (!confirm("¿Eliminar esta conversación?")) return;
                await api.del(`/conversations/${id}`);
                if (convId === id) { setConvId(null); setMessages([]); }
                void refreshConvs();
              }}
              onCreateProject={createProject}
              onImportProject={importProject}
              onLogout={() => void logout()}
              onClose={() => setSidebarOpen(false)}
            />
          </div>
        </div>
      )}

      {/* Columna central: chat */}
      <div className="flex-1 min-w-0 flex flex-col h-full">
        <header
          className="flex items-center gap-2 px-3 py-2 border-b shrink-0"
          style={{ borderColor: "var(--border)", background: "var(--bg-panel)" }}
        >
          <button className="md:hidden p-1.5 rounded-lg" onClick={() => setSidebarOpen(true)} aria-label="Abrir menú">
            <Icon path={ICONS.menu} />
          </button>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold truncate">
              {convs.find((c) => c.id === convId)?.title || "Nueva conversación"}
            </p>
            <p className="text-[11px] truncate" style={{ color: "var(--text-dim)" }}>
              {activeProject ? `Proyecto: ${activeProject.name}` : "Sin proyecto"}
              {usage ? ` · hoy: $${usage.today_cost.toFixed(4)} · ${usage.totals.calls} llamadas hoy` : ""}
            </p>
          </div>
          <button
            onClick={() => setPanelOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs"
            style={{ borderColor: "var(--border)" }}
            title="Panel de tareas, archivos y git"
          >
            <Icon path={ICONS.tasks} size={14} />
            <span className="hidden sm:inline">Panel</span>
            {running && <Spinner size={10} />}
          </button>
        </header>

        {globalError && (
          <div className="px-3 py-1.5 text-xs flex items-center gap-2" style={{ background: "rgba(220,38,38,.08)", color: "#ef4444" }}>
            {globalError}
            <button className="ml-auto" onClick={() => setGlobalError("")}><Icon path={ICONS.close} size={12} /></button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-3 py-4">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center gap-3 px-4">
              <div className="w-12 h-12 rounded-2xl flex items-center justify-center text-white font-bold" style={{ background: "var(--accent)" }}>
                HJ
              </div>
              <h2 className="font-semibold">HacheCode Agent</h2>
              <p className="text-sm max-w-md" style={{ color: "var(--text-dim)" }}>
                Pide cualquier trabajo de programación: revisar, corregir, probar o
                empaquetar. Verás el plan de tareas, cada herramienta ejecutada y la
                evidencia real — con el motor corriendo en tu VPS.
              </p>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto">
              <MessageView messages={messages} running={running} />
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <div className="shrink-0">
          <div className="max-w-3xl mx-auto">
            <Composer
              models={models}
              modelsKey={modelsKey}
              onSend={(t) => void sendMessage(t)}
              onStop={() => void stopTask()}
              onAttach={(f) => void attachZip(f)}
              running={running}
              disabledReason={disabledReason}
              onModelsChanged={() => void refreshModels()}
            />
          </div>
        </div>
      </div>

      {/* Panel derecho: estático en xl+, overlay en pantallas pequeñas */}
      {panelOpen && (
        <>
          {/* overlay móvil */}
          <div className="fixed inset-0 z-40 xl:hidden bg-black/40" onClick={() => setPanelOpen(false)} />
          <div
            className={`
              fixed xl:static inset-y-0 right-0 z-50 xl:z-0
              w-full max-w-md xl:max-w-sm
              border-l flex flex-col h-full
            `}
            style={{ background: "var(--bg-panel)", borderColor: "var(--border)" }}
          >
            <div className="flex items-center border-b shrink-0" style={{ borderColor: "var(--border)" }}>
              {(["tareas", "archivos", "git"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setPanel(t)}
                  className="flex-1 py-2.5 text-xs font-medium capitalize relative"
                  style={{ color: panel === t ? "var(--accent)" : "var(--text-dim)" }}
                >
                  {t === "tareas" ? "Tareas" : t === "archivos" ? "Archivos" : "Git"}
                  {panel === t && (
                    <span className="absolute bottom-0 inset-x-4 h-0.5 rounded-full" style={{ background: "var(--accent)" }} />
                  )}
                </button>
              ))}
              <button className="p-2 mx-1 rounded-lg xl:hidden" onClick={() => setPanelOpen(false)} aria-label="Cerrar panel">
                <Icon path={ICONS.close} size={16} />
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto">
              {panel === "tareas" && (
                <TaskPanel activity={activity} onRetry={(t) => void retryTask(t)} onDownloadZip={downloadZip} />
              )}
              {panel === "archivos" && (
                <FilesPanel project={activeProject} refreshKey={filesKey} />
              )}
              {panel === "git" && (
                <GitPanel project={activeProject} refreshKey={filesKey} />
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ------------------------------ helpers ----------------------------------

function csrfHeader(): string {
  return getCsrf() || "";
}

function resumenDe(result: string | null): string | null {
  if (!result) return null;
  // El resumen final de la tarea V3 es texto; tomamos el bloque tras la línea vacía
  const parts = result.split("\n\n");
  return parts[parts.length - 1] || result;
}

/** Reducer de eventos SSE -> estado de actividad (idempotente con replay). */
function applyEvent(prev: TaskActivity, ev: TaskEvent, historical: boolean): TaskActivity {
  const d = ev.data as Record<string, unknown>;
  const next: TaskActivity = { ...prev, tools: prev.tools, notifs: prev.notifs };
  switch (ev.type) {
    case "plan":
      next.plan = (d.plan as TaskActivity["plan"]) || prev.plan;
      break;
    case "tool": {
      const key = `${ev.id}`;
      if (prev.tools.some((t) => t.key === key)) break; // replay: dedup
      next.tools = [...prev.tools, {
        key, name: String(d.name || ""), ok: d.ok !== false,
        summary: String(d.summary || ""), step: Number(d.step || 0),
      }];
      break;
    }
    case "notify":
      next.notifs = [...prev.notifs, String(d.text || "")];
      break;
    case "plan_incomplete":
      next.planIncompleteNote = String(d.note || "");
      break;
    case "status": {
      const st = String(d.status || prev.status);
      next.status = st as TaskActivity["status"];
      if (d.summary) next.summary = String(d.summary);
      if (d.error) next.error = String(d.error);
      if (typeof d.steps === "number") next.steps = d.steps;
      if (typeof d.cost === "number") next.cost = d.cost;
      if (Array.isArray(d.files_touched)) next.filesTouched = d.files_touched as string[];
      if (typeof d.commands === "number") next.commandsCount = d.commands;
      if (typeof d.tests === "number") next.testsCount = d.tests;
      if (st === "done" || st === "failed") next.zipAvailable = prev.zipAvailable;
      break;
    }
    default:
      break;
  }
  void historical;
  return next;
}
