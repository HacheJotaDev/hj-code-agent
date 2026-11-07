"use client";

/** Explorador de archivos estilo IDE: árbol, editor Monaco, guardado real,
 * descarga, diff git del archivo, subida de ZIP y exportación. */
import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import type { FileContent, Project, TreeNode } from "@/lib/types";
import { api, getCsrf } from "@/lib/api";
import { ICONS, Icon, Spinner } from "./ui";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-xs" style={{ color: "var(--text-dim)" }}>
      <Spinner /> Cargando editor…
    </div>
  ),
});

function languageOf(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() || "";
  const map: Record<string, string> = {
    py: "python", js: "javascript", mjs: "javascript", cjs: "javascript",
    ts: "typescript", tsx: "typescript", jsx: "javascript", json: "json",
    md: "markdown", css: "css", html: "html", yml: "yaml", yaml: "yaml",
    toml: "ini", ini: "ini", sh: "shell", bash: "shell", sql: "sql",
    go: "go", rs: "rust", java: "java", c: "c", h: "c", cpp: "cpp", rb: "ruby",
    php: "php", env: "ini", txt: "plaintext", xml: "xml",
  };
  return map[ext] || "plaintext";
}

function TreeItem({
  node,
  path,
  depth,
  selected,
  onSelect,
  expanded,
  toggleDir,
}: {
  node: TreeNode;
  path: string;
  depth: number;
  selected: string;
  onSelect: (p: string) => void;
  expanded: Set<string>;
  toggleDir: (p: string) => void;
}) {
  const p = path ? `${path}/${node.name}` : node.name;
  const isOpen = expanded.has(p);
  if (node.type === "dir") {
    return (
      <div>
        <button
          onClick={() => toggleDir(p)}
          className="w-full text-left flex items-center gap-1 px-1.5 py-1 rounded hover:bg-black/5 dark:hover:bg-white/10 text-xs"
          style={{ paddingLeft: depth * 12 + 6 }}
        >
          <Icon path={ICONS.chevron} size={11} className={`transition-transform ${isOpen ? "rotate-90" : ""}`} />
          <Icon path={ICONS.folder} size={13} />
          <span className="truncate">{node.name}</span>
        </button>
        {isOpen &&
          node.children?.map((c) => (
            <TreeItem key={c.name + p} node={c} path={p} depth={depth + 1} selected={selected} onSelect={onSelect} expanded={expanded} toggleDir={toggleDir} />
          ))}
      </div>
    );
  }
  return (
    <button
      onClick={() => onSelect(p)}
      className="w-full text-left flex items-center gap-1.5 px-1.5 py-1 rounded hover:bg-black/5 dark:hover:bg-white/10 text-xs"
      style={{ paddingLeft: depth * 12 + 20, background: p === selected ? "var(--accent-soft)" : undefined }}
    >
      <Icon path={ICONS.file} size={12} />
      <span className="truncate" style={{ color: p === selected ? "var(--accent)" : undefined }}>{node.name}</span>
    </button>
  );
}

export default function FilesPanel({
  project,
  refreshKey,
}: {
  project: Project | null;
  refreshKey: number;
}) {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState("");
  const [content, setContent] = useState<FileContent | null>(null);
  const [draft, setDraft] = useState("");
  const [diff, setDiff] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const loadTree = useCallback(async () => {
    if (!project) return;
    try {
      const r = await api.get<{ tree: TreeNode }>(`/projects/${project.id}/tree`);
      setTree(r.tree);
      // auto-expandir la raíz
      setExpanded((prev) => {
        if (prev.size) return prev;
        const s = new Set<string>();
        r.tree.children?.filter((c) => c.type === "dir").forEach((c) => {
          s.add(c.name);
        });
        return s;
      });
    } catch {
      setTree(null);
    }
  }, [project]);

  useEffect(() => {
    void loadTree();
    setSelected("");
    setContent(null);
    setDiff(null);
  }, [loadTree, refreshKey]);

  async function openFile(path: string) {
    setSelected(path);
    setDiff(null);
    setMsg("");
    try {
      const r = await api.get<FileContent>(`/projects/${project!.id}/file?path=${encodeURIComponent(path)}`);
      setContent(r);
      setDraft(r.binary ? "" : r.content || "");
    } catch (e) {
      setContent(null);
      setMsg(String(e instanceof Error ? e.message : e));
    }
  }

  async function save() {
    if (!project || !selected || content?.binary) return;
    setBusy(true);
    try {
      await api.put(`/projects/${project.id}/file`, { path: selected, content: draft });
      setMsg("Guardado ✓ (los cambios quedan en el workspace real)");
      void loadTree();
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function showDiff() {
    if (!project || !selected) return;
    try {
      const r = await api.get<{ diff: string }>(`/projects/${project.id}/git/diff?path=${encodeURIComponent(selected)}`);
      setDiff(r.diff);
    } catch (e) {
      setDiff(`(sin diff: ${e instanceof Error ? e.message : e})`);
    }
  }

  async function download() {
    if (!project || !selected) return;
    window.open(api.downloadUrl(`/projects/${project.id}/raw?path=${encodeURIComponent(selected)}`), "_blank");
  }

  async function del() {
    if (!project || !selected) return;
    if (!confirm(`¿Borrar ${selected}?`)) return;
    try {
      await api.del(`/projects/${project.id}/file?path=${encodeURIComponent(selected)}`);
      setSelected("");
      setContent(null);
      setDiff(null);
      void loadTree();
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
    }
  }

  function uploadZip(file: File) {
    if (!project) return;
    const fd = new FormData();
    fd.append("file", file);
    fetch(api.downloadUrl(`/projects/${project.id}/upload`), {
      method: "POST",
      body: fd,
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrf() || "" },
    }).then(async (res) => {
      if (res.ok) {
        setMsg("ZIP extraído en el workspace ✓");
        void loadTree();
      } else {
        const d = await res.json().catch(() => ({}));
        setMsg(`Error: ${d.detail || res.status}`);
      }
    });
  }

  function exportZip() {
    if (!project) return;
    window.open(api.downloadUrl(`/projects/${project.id}/export`), "_blank");
  }

  const diffLines = useMemo(() => diff?.split("\n") ?? [], [diff]);

  return (
    <div className="flex flex-col h-full">
      {!project ? (
        <p className="p-4 text-xs" style={{ color: "var(--text-dim)" }}>Selecciona un proyecto.</p>
      ) : (
        <>
          <div className="flex items-center gap-1 px-2 py-2 border-b flex-wrap" style={{ borderColor: "var(--border)" }}>
            <label className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] cursor-pointer" style={{ borderColor: "var(--border)" }}>
              <Icon path={ICONS.upload} size={12} /> Subir ZIP
              <input
                type="file"
                accept=".zip,.tar.gz,.tgz,.tar"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadZip(f);
                  e.target.value = "";
                }}
              />
            </label>
            <button onClick={exportZip} className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px]" style={{ borderColor: "var(--border)" }}>
              <Icon path={ICONS.download} size={12} /> Exportar
            </button>
            <button onClick={() => void loadTree()} className="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/10" title="Refrescar árbol">
              <Icon path={ICONS.refresh} size={13} />
            </button>
            {msg && <span className="text-[10.5px] flex-1 min-w-0 truncate" style={{ color: "var(--accent)" }}>{msg}</span>}
          </div>
          <div className="flex flex-1 min-h-0">
            <div className="w-44 sm:w-52 border-r overflow-y-auto py-1.5 px-1 shrink-0" style={{ borderColor: "var(--border)" }}>
              {tree?.children?.map((c) => (
                <TreeItem
                  key={c.name}
                  node={c}
                  path=""
                  depth={0}
                  selected={selected}
                  onSelect={(p) => void openFile(p)}
                  expanded={expanded}
                  toggleDir={(p) =>
                    setExpanded((prev) => {
                      const s = new Set(prev);
                      if (s.has(p)) s.delete(p);
                      else s.add(p);
                      return s;
                    })
                  }
                />
              ))}
              {tree?.truncated && <p className="text-[10px] px-2 py-1" style={{ color: "var(--text-dim)" }}>Árbol truncado (2000 entradas)</p>}
            </div>
            <div className="flex-1 min-w-0 flex flex-col">
              {selected ? (
                <>
                  <div className="flex items-center gap-1 px-2 py-1.5 border-b text-[11px]" style={{ borderColor: "var(--border)" }}>
                    <span className="font-mono truncate flex-1" style={{ color: "var(--text-dim)" }}>{selected}</span>
                    <button onClick={save} disabled={busy || content?.binary} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 font-medium disabled:opacity-40" style={{ borderColor: "var(--accent)", color: "var(--accent)" }}>
                      <Icon path={ICONS.check} size={12} /> Guardar
                    </button>
                    <button onClick={showDiff} className="inline-flex items-center gap-1 rounded-md border px-2 py-1" style={{ borderColor: "var(--border)" }}>
                      <Icon path={ICONS.git} size={12} /> Diff
                    </button>
                    <button onClick={download} className="p-1.5 rounded-md hover:bg-black/5 dark:hover:bg-white/10" title="Descargar archivo">
                      <Icon path={ICONS.download} size={13} />
                    </button>
                    <button onClick={del} className="p-1.5 rounded-md hover:bg-black/5 dark:hover:bg-white/10" title="Borrar archivo">
                      <Icon path={ICONS.trash} size={13} />
                    </button>
                  </div>
                  {diff ? (
                    <div className="flex-1 overflow-auto p-2 font-mono text-[10.5px] leading-relaxed">
                      {diffLines.map((l, i) => (
                        <div
                          key={i}
                          className={
                            l.startsWith("+") && !l.startsWith("+++") ? "diff-add"
                            : l.startsWith("-") && !l.startsWith("---") ? "diff-del"
                            : "opacity-70"
                          }
                        >
                          {l || " "}
                        </div>
                      ))}
                    </div>
                  ) : content?.binary ? (
                    <p className="p-3 text-xs" style={{ color: "var(--text-dim)" }}>
                      Archivo binario ({content.size} bytes) — usa descargar.
                    </p>
                  ) : (
                    <div className="flex-1 min-h-0">
                      <MonacoEditor
                        height="100%"
                        language={languageOf(selected)}
                        value={draft}
                        theme="vs-dark"
                        onChange={(v) => setDraft(v ?? "")}
                        options={{
                          fontSize: 12.5,
                          minimap: { enabled: false },
                          wordWrap: "on",
                          automaticLayout: true,
                          tabSize: 4,
                          scrollBeyondLastLine: false,
                          readOnly: content?.truncated,
                        }}
                      />
                    </div>
                  )}
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-xs" style={{ color: "var(--text-dim)" }}>
                  Selecciona un archivo del árbol
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

