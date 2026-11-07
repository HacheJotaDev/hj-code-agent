"use client";

/** Panel Git: estado, historial, diff, ramas, commit y push en DOS pasos
 * (vista previa de repo/rama/commits + confirmación explícita del usuario). */
import { useCallback, useEffect, useState } from "react";
import type { GitCommit, GitStatus, PushPreview, Project } from "@/lib/types";
import { api } from "@/lib/api";
import { ICONS, Icon } from "./ui";

export default function GitPanel({
  project,
  refreshKey,
}: {
  project: Project | null;
  refreshKey: number;
}) {
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [commits, setCommits] = useState<GitCommit[]>([]);
  const [diff, setDiff] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [branchName, setBranchName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [confirmPush, setConfirmPush] = useState<PushPreview | null>(null);

  const load = useCallback(async () => {
    if (!project) return;
    try {
      const st = await api.get<GitStatus>(`/projects/${project.id}/git/status`);
      setStatus(st);
      if (st.is_repo) {
        const log = await api.get<{ commits: GitCommit[] }>(`/projects/${project.id}/git/log?limit=15`);
        setCommits(log.commits);
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }, [project]);

  useEffect(() => {
    void load();
    setDiff(null);
    setConfirmPush(null);
  }, [load, refreshKey]);

  async function run(fn: () => Promise<unknown>, okMsg: string) {
    setBusy(true);
    setMsg("");
    try {
      await fn();
      setMsg(okMsg);
      await load();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function requestPush() {
    if (!project) return;
    await run(async () => {
      const prev = await api.post<PushPreview>(`/projects/${project.id}/git/push-request`, {});
      setConfirmPush(prev);
    }, "");
  }

  async function confirmPushGo() {
    if (!project || !confirmPush) return;
    const token = confirmPush.push_token;
    await run(async () => {
      const r = await api.post<{ message: string }>(`/projects/${project.id}/git/push-confirm`, { token });
      setConfirmPush(null);
      setMsg(r.message);
    }, "");
  }

  if (!project) {
    return <p className="p-4 text-xs" style={{ color: "var(--text-dim)" }}>Selecciona un proyecto.</p>;
  }

  const statusLines = (status?.status || "").split("\n").filter(Boolean);

  return (
    <div className="flex flex-col gap-3 p-3 text-sm overflow-y-auto">
      <div className="flex items-center gap-2">
        <Icon path={ICONS.git} size={15} />
        <span className="font-semibold text-xs uppercase tracking-wide">Git</span>
        <button onClick={() => void load()} className="ml-auto p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/10">
          <Icon path={ICONS.refresh} size={13} />
        </button>
      </div>

      {msg && (
        <p className="rounded-lg px-3 py-2 text-xs" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
          {msg}
        </p>
      )}

      {!status?.is_repo ? (
        <div className="flex flex-col gap-2 text-xs">
          <p style={{ color: "var(--text-dim)" }}>Este proyecto aún no es un repositorio git o no tiene remoto.</p>
          <div className="flex gap-1.5">
            <input
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/usuario/repo.git"
              className="flex-1 rounded-lg border px-2 py-1.5 bg-transparent text-xs"
              style={{ borderColor: "var(--border)" }}
            />
          </div>
          <div className="flex gap-1.5">
            <button
              onClick={() => void run(async () => {
                await api.post(`/projects/${project.id}/git/repo`, { url: repoUrl.trim() });
              }, "Repositorio conectado")}
              disabled={!repoUrl.trim() || busy}
              className="rounded-lg border px-2.5 py-1.5 text-xs disabled:opacity-40"
              style={{ borderColor: "var(--border)" }}
            >
              Conectar remoto
            </button>
            <button
              onClick={() => void run(async () => {
                await api.post(`/projects/${project.id}/git/repo`, { url: repoUrl.trim() });
                await api.post(`/projects/${project.id}/git/clone`, { url: repoUrl.trim() });
              }, "Clonado en el workspace")}
              disabled={!repoUrl.trim() || busy}
              className="rounded-lg border px-2.5 py-1.5 text-xs disabled:opacity-40"
              style={{ borderColor: "var(--border)" }}
            >
              Conectar y clonar
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="rounded-xl border p-2.5 text-xs" style={{ borderColor: "var(--border)" }}>
            <p className="font-mono mb-1" style={{ color: "var(--accent)" }}>{status.branch || "(sin rama)"}</p>
            {status.repo_url && (
              <p className="truncate" style={{ color: "var(--text-dim)" }}>{status.repo_url}</p>
            )}
            {statusLines.length > 0 && (
              <pre className="mt-1.5 whitespace-pre-wrap font-mono text-[10.5px] max-h-32 overflow-y-auto" style={{ color: "var(--text-dim)" }}>
                {statusLines.join("\n")}
              </pre>
            )}
          </div>

          <div className="flex flex-wrap gap-1.5">
            <input
              value={branchName}
              onChange={(e) => setBranchName(e.target.value)}
              placeholder="nueva-rama"
              className="rounded-lg border px-2 py-1.5 text-xs bg-transparent w-36"
              style={{ borderColor: "var(--border)" }}
            />
            <button
              onClick={() => void run(async () => {
                await api.post(`/projects/${project.id}/git/branch`, { name: branchName.trim() });
                setBranchName("");
              }, "Rama creada/cambiada")}
              disabled={!branchName.trim() || busy}
              className="rounded-lg border px-2.5 py-1.5 text-xs disabled:opacity-40"
              style={{ borderColor: "var(--border)" }}
            >
              Crear rama
            </button>
            <button
              onClick={() => void run(() => api.get<{ diff: string }>(`/projects/${project.id}/git/diff`).then((r) => setDiff(r.diff)), "")}
              className="rounded-lg border px-2.5 py-1.5 text-xs"
              style={{ borderColor: "var(--border)" }}
            >
              Ver diff
            </button>
            <button
              onClick={() => void run(async () => {
                await api.post(`/projects/${project.id}/git/commit`, { message: `Commit desde la web (${new Date().toLocaleString("es")})` });
              }, "Commit creado (todo lo pendiente)")}
              disabled={busy}
              className="rounded-lg border px-2.5 py-1.5 text-xs"
              style={{ borderColor: "var(--border)" }}
            >
              Commit
            </button>
            <button
              onClick={() => void requestPush()}
              disabled={busy}
              className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-white disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              Push…
            </button>
          </div>

          {confirmPush && (
            <div className="rounded-xl border p-3 text-xs flex flex-col gap-2" style={{ borderColor: "#d97706", background: "rgba(217,119,6,.06)" }}>
              <p className="font-semibold" style={{ color: "#d97706" }}>Autorización de push requerida</p>
              <p>Repositorio: <span className="font-mono">{confirmPush.repo_url}</span></p>
              <p>Rama: <span className="font-mono">{confirmPush.branch}</span></p>
              <p>Commits a publicar: {confirmPush.commits.length}</p>
              <ul className="font-mono text-[10.5px] max-h-24 overflow-y-auto" style={{ color: "var(--text-dim)" }}>
                {confirmPush.commits.map((c) => (
                  <li key={c.hash}>{c.hash.slice(0, 8)} {c.subject}</li>
                ))}
              </ul>
              {confirmPush.warning && <p style={{ color: "#d97706" }}>⚠ {confirmPush.warning}</p>}
              <div className="flex gap-2">
                <button
                  onClick={() => void confirmPushGo()}
                  disabled={busy}
                  className="rounded-lg px-3 py-1.5 font-medium text-white"
                  style={{ background: "#dc2626" }}
                >
                  Confirmar push
                </button>
                <button
                  onClick={() => setConfirmPush(null)}
                  className="rounded-lg border px-3 py-1.5"
                  style={{ borderColor: "var(--border)" }}
                >
                  Cancelar
                </button>
              </div>
            </div>
          )}

          {diff && (
            <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)" }}>
              <div className="flex items-center justify-between px-3 py-1.5 text-xs" style={{ background: "var(--bg-sidebar)" }}>
                <span className="font-medium">Diff del proyecto</span>
                <button onClick={() => setDiff(null)}><Icon path={ICONS.close} size={13} /></button>
              </div>
              <div className="overflow-auto max-h-72 p-2 font-mono text-[10.5px] leading-relaxed">
                {diff.split("\n").map((l, i) => (
                  <div
                    key={i}
                    className={l.startsWith("+") && !l.startsWith("+++") ? "diff-add" : l.startsWith("-") && !l.startsWith("---") ? "diff-del" : "opacity-70"}
                  >
                    {l || " "}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-dim)" }}>
              Historial
            </span>
            <ul className="mt-1.5 flex flex-col gap-1.5">
              {commits.map((c) => (
                <li key={c.hash} className="rounded-lg border px-2.5 py-1.5 text-xs" style={{ borderColor: "var(--border)" }}>
                  <p className="truncate font-medium">{c.subject}</p>
                  <p className="text-[10px]" style={{ color: "var(--text-dim)" }}>
                    <span className="font-mono">{c.hash.slice(0, 8)}</span> · {c.author} · {c.date?.slice(0, 16).replace("T", " ")}
                  </p>
                </li>
              ))}
              {commits.length === 0 && <li className="text-xs" style={{ color: "var(--text-dim)" }}>Sin commits todavía.</li>}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
