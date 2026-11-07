"use client";

/** Composer: campo grande, adjuntar (ZIP), selector de modelo, enviar/detener. */
import { useRef, useState } from "react";
import type { ModelsResponse } from "@/lib/types";
import { ICONS, Icon, Spinner } from "./ui";
import ModelSelector from "./ModelSelector";

export default function Composer({
  models,
  modelsKey,
  onSend,
  onStop,
  onAttach,
  running,
  disabledReason,
  onModelsChanged,
}: {
  models: ModelsResponse | null;
  modelsKey: number;
  onSend: (text: string) => void;
  onStop: () => void;
  onAttach: (file: File) => void;
  running: boolean;
  disabledReason: string | null;
  onModelsChanged: () => void;
}) {
  const [text, setText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  function autoResize() {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
  }

  function send() {
    const t = text.trim();
    if (!t || running || disabledReason) return;
    onSend(t);
    setText("");
    requestAnimationFrame(autoResize);
  }

  return (
    <div className="safe-bottom px-3 pt-1" style={{ background: "var(--bg)" }}>
      {disabledReason && (
        <p className="text-[11px] mb-1 px-1" style={{ color: "var(--text-dim)" }}>
          {disabledReason}
        </p>
      )}
      <div
        className="rounded-2xl border p-2 flex flex-col gap-1.5"
        style={{ background: "var(--bg-panel)", borderColor: "var(--border)" }}
      >
        <textarea
          ref={taRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            autoResize();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
          rows={1}
          placeholder="Describe la tarea: 'revisa el proyecto, corrige errores, ejecuta pruebas y genera un ZIP'…"
          className="w-full resize-none bg-transparent outline-none text-sm px-2 pt-1.5 min-h-[40px] max-h-[180px]"
        />
        <div className="flex items-center gap-1.5 px-1">
          <input
            ref={fileRef}
            type="file"
            accept=".zip,.tar.gz,.tgz,.tar"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onAttach(f);
              e.target.value = "";
            }}
          />
          <button
            onClick={() => fileRef.current?.click()}
            className="p-2 rounded-lg hover:bg-black/5 dark:hover:bg-white/10"
            title="Subir ZIP / archivos al proyecto"
            aria-label="Adjuntar archivos"
          >
            <Icon path={ICONS.paperclip} size={17} />
          </button>
          <ModelSelector key={modelsKey} models={models} onChange={onModelsChanged} />
          <div className="flex-1" />
          {running ? (
            <button
              onClick={onStop}
              className="flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-sm font-medium text-white"
              style={{ background: "#dc2626" }}
              title="Detener la ejecución"
            >
              <Icon path={ICONS.stop} size={15} /> Detener
            </button>
          ) : (
            <button
              onClick={send}
              disabled={!text.trim() || !!disabledReason}
              className="flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-sm font-medium text-white disabled:opacity-40"
              style={{ background: "var(--accent)" }}
              title="Enviar"
            >
              Enviar <Icon path={ICONS.send} size={15} />
            </button>
          )}
        </div>
      </div>
      <p className="text-[10px] text-center mt-1 mb-0.5" style={{ color: "var(--text-dim)" }}>
        Enter envía · Shift+Enter salto de línea
      </p>
    </div>
  );
}
