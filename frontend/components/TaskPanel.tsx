"use client";

/** Panel de tareas: plan visual con estados REALES + bloques de actividad
 * desplegables con evidencia (salidas de comandos, archivos, pruebas).
 *
 * El plan lo declara el propio agente con update_plan; la UI nunca marca
 * tareas completadas por su cuenta (ni al agotar el límite de pasos).
 */
import { useMemo, useState } from "react";
import type { PlanStep, PlanStatus, TaskStatus } from "@/lib/types";
import { ICONS, Icon, Spinner, StatusChip, ToolLabel } from "./ui";

export interface ToolActivity {
  key: string;
  name: string;
  ok: boolean;
  summary: string;
  step: number;
}

export interface TaskActivity {
  taskId: number;
  status: TaskStatus;
  plan: PlanStep[];
  tools: ToolActivity[];
  notifs: string[];
  summary: string | null;
  error: string | null;
  steps: number | null;
  cost: number | null;
  filesTouched: string[];
  commandsCount: number | null;
  testsCount: number | null;
  planIncompleteNote: string | null;
  zipAvailable: boolean;
}

function PlanIcon({ status }: { status: PlanStatus }) {
  const box = "w-4.5 h-4.5 w-[18px] h-[18px] rounded-full flex items-center justify-center shrink-0";
  switch (status) {
    case "done":
      return <span className={`${box} text-white`} style={{ background: "var(--accent)" }}><Icon path={ICONS.check} size={11} /></span>;
    case "in_progress":
      return <span className={`${box}`} style={{ color: "#2563eb", border: "2px solid #2563eb" }}><Spinner size={10} /></span>;
    case "failed":
      return <span className={`${box} text-white`} style={{ background: "#dc2626" }}><Icon path={ICONS.x} size={10} /></span>;
    case "partial":
      return <span className={`${box}`} style={{ background: "#d97706", color: "#fff", fontSize: 9, fontWeight: 700 }}>½</span>;
    default:
      return <span className={box} style={{ border: "2px solid var(--border)" }} />;
  }
}

function ActivityBlock({
  title,
  count,
  children,
  defaultOpen = false,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (count === 0) return null;
  return (
    <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium"
        style={{ background: "var(--bg-sidebar)" }}
      >
        <Icon path={open ? ICONS.chevronDown : ICONS.chevron} size={13} />
        {title}
        <span
          className="ml-auto rounded-full px-2 py-0.5 text-[10px]"
          style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
        >
          {count}
        </span>
      </button>
      {open && <div className="px-3 py-2 text-xs flex flex-col gap-1.5">{children}</div>}
    </div>
  );
}

function CmdLine({ cmd, out, ok }: { cmd?: string; out: string; ok: boolean }) {
  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor: "var(--border)" }}>
      {cmd && (
        <p className="px-2 py-1 font-mono text-[11px] flex items-center gap-1.5" style={{ background: "var(--bg-sidebar)" }}>
          <span style={{ color: ok ? "var(--accent)" : "#ef4444" }}>{ok ? "$" : "✗"}</span>
          {cmd}
        </p>
      )}
      <pre className="px-2 py-1.5 overflow-x-auto max-h-56 text-[10.5px] leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-dim)" }}>
        {out.slice(0, 4000)}
      </pre>
    </div>
  );
}

function parseResult(raw: string): { ok: boolean; result: string } {
  try {
    const p = JSON.parse(raw);
    if (p && typeof p === "object") {
      return { ok: p.ok !== false, result: typeof p.result === "string" ? p.result : JSON.stringify(p.result ?? p, null, 2) };
    }
  } catch { /* plain */ }
  return { ok: true, result: raw };
}

export default function TaskPanel({
  activity,
  onRetry,
  onDownloadZip,
}: {
  activity: TaskActivity | null;
  onRetry: (taskId: number) => void;
  onDownloadZip: (taskId: number) => void;
}) {
  const grouped = useMemo(() => {
    const g = {
      explored: [] as ToolActivity[],
      modified: [] as ToolActivity[],
      commands: [] as ToolActivity[],
      tests: [] as ToolActivity[],
      others: [] as ToolActivity[],
    };
    if (!activity) return g;
    for (const t of activity.tools) {
      const r = parseResult(t.summary);
      if (["list_files", "read_file", "search_files", "search_code"].includes(t.name)) g.explored.push(t);
      else if (["write_file", "edit_file", "apply_patch", "move_file", "delete_file"].includes(t.name)) g.modified.push(t);
      else if (t.name === "run_tests") g.tests.push(t);
      else if (["execute_command", "install_dependencies", "run_build"].includes(t.name)) g.commands.push(t);
      else g.others.push(t);
    }
    return g;
  }, [activity]);

  if (!activity) {
    return (
      <div className="p-4 text-xs" style={{ color: "var(--text-dim)" }}>
        Sin tarea activa. Envía una instrucción y el plan de trabajo aparecerá aquí,
        actualizado en vivo por el agente.
      </div>
    );
  }

  const done = activity.plan.filter((p) => p.status === "done").length;
  const planProgress = activity.plan.length ? Math.round((done / activity.plan.length) * 100) : 0;

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-center gap-2 flex-wrap">
        <StatusChip status={activity.status} />
        {activity.steps !== null && (
          <span className="text-[11px]" style={{ color: "var(--text-dim)" }}>Pasos: {activity.steps}</span>
        )}
        {activity.cost !== null && (
          <span className="text-[11px]" style={{ color: "var(--text-dim)" }}>Coste: ${activity.cost.toFixed(4)}</span>
        )}
        {activity.zipAvailable && (
          <button
            onClick={() => onDownloadZip(activity.taskId)}
            className="ml-auto inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium"
            style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
          >
            <Icon path={ICONS.download} size={12} /> Descargar ZIP
          </button>
        )}
      </div>

      {activity.plan.length > 0 && (
        <div className="rounded-xl border p-3" style={{ borderColor: "var(--border)" }}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold flex items-center gap-1.5">
              <Icon path={ICONS.tasks} size={14} /> Tareas — {activity.plan.length}
            </span>
            <span className="text-[11px]" style={{ color: "var(--text-dim)" }}>{done}/{activity.plan.length}</span>
          </div>
          <div className="h-1 rounded-full mb-3 overflow-hidden" style={{ background: "var(--border)" }}>
            <div className="h-full rounded-full transition-all" style={{ width: `${planProgress}%`, background: "var(--accent)" }} />
          </div>
          <ul className="flex flex-col gap-2">
            {activity.plan.map((p, i) => (
              <li key={i} className="flex items-center gap-2.5 text-sm">
                <PlanIcon status={p.status} />
                <span className={p.status === "done" ? "line-through opacity-60" : ""}>{p.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {activity.planIncompleteNote && (
        <p className="rounded-lg px-3 py-2 text-xs flex items-start gap-2" style={{ background: "rgba(217,119,6,.1)", color: "#d97706" }}>
          <Icon path={ICONS.alert} size={13} className="mt-0.5 shrink-0" />
          {activity.planIncompleteNote}
        </p>
      )}

      {activity.error && (
        <p className="rounded-lg px-3 py-2 text-xs" style={{ background: "rgba(220,38,38,.08)", color: "#ef4444" }}>
          {activity.error}
        </p>
      )}

      <ActivityBlock title="Archivos explorados" count={grouped.explored.length}>
        {grouped.explored.map((t) => {
          const r = parseResult(t.summary);
          return <CmdLine key={t.key} out={r.result.slice(0, 800)} ok={r.ok} />;
        })}
      </ActivityBlock>

      <ActivityBlock
        title="Archivos modificados"
        count={activity.filesTouched.length || grouped.modified.length}
        defaultOpen
      >
        {(activity.filesTouched.length ? activity.filesTouched : grouped.modified.map((m) => m.summary.split("\n")[0] || "")).map((f, i) => (
          <p key={i} className="font-mono truncate flex items-center gap-1.5">
            <Icon path={ICONS.file} size={12} /> {f}
          </p>
        ))}
      </ActivityBlock>

      <ActivityBlock title="Comandos ejecutados" count={grouped.commands.length}>
        {grouped.commands.map((t) => {
          const r = parseResult(t.summary);
          const cmdMatch = r.result.match(/^\$?\s*(.+)$/m);
          return (
            <CmdLine key={t.key} out={r.result.slice(0, 1500)} ok={r.ok} />
          );
        })}
      </ActivityBlock>

      <ActivityBlock title="Pruebas" count={activity.testsCount ?? grouped.tests.length}>
        {grouped.tests.map((t) => {
          const r = parseResult(t.summary);
          return <CmdLine key={t.key} out={r.result.slice(0, 2500)} ok={r.ok} />;
        })}
      </ActivityBlock>

      <ActivityBlock title="Otras herramientas" count={grouped.others.length}>
        {grouped.others.map((t) => {
          const r = parseResult(t.summary);
          return (
            <div key={t.key}>
              <p className="font-medium"><ToolLabel name={t.name} /></p>
              <pre className="whitespace-pre-wrap text-[10.5px] max-h-40 overflow-y-auto" style={{ color: "var(--text-dim)" }}>
                {r.result.slice(0, 1200)}
              </pre>
            </div>
          );
        })}
      </ActivityBlock>

      {activity.notifs.length > 0 && (
        <ActivityBlock title="Avisos del agente" count={activity.notifs.length}>
          {activity.notifs.map((n, i) => (
            <p key={i} style={{ color: "var(--text-dim)" }}>• {n}</p>
          ))}
        </ActivityBlock>
      )}

      {activity.summary && (
        <div className="rounded-xl border p-3 text-sm md-body" style={{ borderColor: "var(--border)" }}>
          <div className="whitespace-pre-wrap">{activity.summary}</div>
        </div>
      )}

      {["failed", "interrupted", "cancelled"].includes(activity.status) && (
        <button
          onClick={() => onRetry(activity.taskId)}
          className="self-start inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-sm font-medium"
          style={{ borderColor: "var(--border)" }}
        >
          <Icon path={ICONS.refresh} size={14} /> Continuar / reintentar
        </button>
      )}
    </div>
  );
}
