"use client";

/** Piezas de UI compartidas (iconos SVG inline, sin dependencias extra). */

export function Icon({ path, size = 18, className = "" }: {
  path: string; size?: number; className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d={path} />
    </svg>
  );
}

export const ICONS = {
  plus: "M12 5v14M5 12h14",
  send: "M4.5 12h13M12 5.5l6.5 6.5-6.5 6.5",
  stop: "M7 7h10v10H7z",
  menu: "M4 6h16M4 12h16M4 18h16",
  close: "M6 6l12 12M18 6L6 18",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5zM14 3v5h5",
  chat: "M21 12a8 8 0 0 1-8 8H5l-2 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8z",
  tasks: "M9 6h11M9 12h11M9 18h11M4 6l1.2 1.2L7.5 5M4 12l1.2 1.2L7.5 11M4 18l1.2 1.2L7.5 17",
  git: "M6 3v12M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9v1a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5",
  paperclip: "M21 11.5l-8.5 8.5a5 5 0 0 1-7-7l8.5-8.5a3.5 3.5 0 1 1 5 5L10.5 18a2 2 0 1 1-2.8-2.8L16 7",
  sun: "M12 4V2m0 20v-2m8-8h2M2 12h2m13.7-5.7l1.4-1.4M4.9 19.1l1.4-1.4m0-11.4L4.9 4.9m14.2 14.2l-1.4-1.4M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8z",
  moon: "M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  refresh: "M21 12a9 9 0 1 1-2.6-6.3M21 3v6h-6",
  chevron: "M9 6l6 6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13M9 7V4h6v3",
  upload: "M12 16V4m0 0L7 9m5-5l5 5M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",
  download: "M12 4v12m0 0l5-5m-5 5l-5-5M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",
  play: "M8 5.5v13l11-6.5-11-6.5z",
  check: "M4 12.5l5 5L20 6.5",
  x: "M6 6l12 12M18 6L6 18",
  clock: "M12 8v4l3 3M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
  alert: "M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  brain: "M12 5a3 3 0 1 0-3 3 3 3 0 1 0 3 3m0-6a3 3 0 1 1 3 3 3 3 0 1 1-3 3m0 0v9m-3-3h6",
  sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z",
};

export function StatusChip({ status }: { status: string }) {
  const map: Record<string, { label: string; color: string; bg: string }> = {
    queued: { label: "En cola", color: "#d97706", bg: "rgba(217,119,6,.1)" },
    running: { label: "Ejecutando", color: "#2563eb", bg: "rgba(37,99,235,.1)" },
    done: { label: "Completada", color: "#059669", bg: "rgba(5,150,105,.1)" },
    failed: { label: "Fallida", color: "#dc2626", bg: "rgba(220,38,38,.1)" },
    cancelled: { label: "Cancelada", color: "#71717a", bg: "rgba(113,113,122,.12)" },
    interrupted: { label: "Interrumpida", color: "#d97706", bg: "rgba(217,119,6,.1)" },
  };
  const s = map[status] || { label: status, color: "#71717a", bg: "rgba(113,113,122,.12)" };
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ color: s.color, background: s.bg }}
    >
      {status === "running" && <Spinner size={10} />}
      {s.label}
    </span>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="animate-spin" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" fill="none" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  );
}

export function ThemeToggle() {
  function toggle() {
    const root = document.documentElement;
    const dark = root.classList.toggle("dark");
    try {
      localStorage.setItem("hj-theme", dark ? "dark" : "light");
    } catch { /* sin localStorage */ }
  }
  return (
    <button
      onClick={toggle}
      className="p-2 rounded-lg hover:bg-black/5 dark:hover:bg-white/10"
      title="Tema claro/oscuro"
      aria-label="Cambiar tema"
    >
      <span className="dark:hidden"><Icon path={ICONS.moon} /></span>
      <span className="hidden dark:inline"><Icon path={ICONS.sun} /></span>
    </button>
  );
}

export function ToolLabel({ name }: { name: string }) {
  const map: Record<string, string> = {
    list_files: "Listó archivos",
    read_file: "Leyó archivo",
    write_file: "Escribió archivo",
    edit_file: "Editó archivo",
    apply_patch: "Aplicó parche",
    search_files: "Buscó archivos",
    search_code: "Buscó código",
    create_directory: "Creó carpeta",
    move_file: "Movió archivo",
    delete_file: "Borró archivo",
    execute_command: "Ejecutó comando",
    install_dependencies: "Instaló dependencias",
    run_tests: "Ejecutó pruebas",
    run_build: "Compiló",
    git_status: "Estado git",
    git_diff: "Diff git",
    git_branch: "Rama git",
    git_commit: "Commit git",
    get_task_logs: "Registros de tarea",
    export_zip: "Exportó ZIP",
    update_plan: "Actualizó plan",
  };
  return <>{map[name] || name}</>;
}
