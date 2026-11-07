"use client";

/** Selector de modelo: catálogo REAL del proveedor activo (nunca inventado). */
import { useEffect, useRef, useState } from "react";
import type { ModelsResponse } from "@/lib/types";
import { api } from "@/lib/api";
import { ICONS, Icon, Spinner } from "./ui";

export default function ModelSelector({
  models,
  onChange,
}: {
  models: ModelsResponse | null;
  onChange: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  async function select(modelId: string) {
    setOpen(false);
    setLoading(true);
    try {
      await api.post("/models/select", { model: modelId, provider: models?.provider });
      onChange();
    } finally {
      setLoading(false);
    }
  }

  const selected = models?.selected || "";
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs max-w-[190px] sm:max-w-[260px]"
        style={{ borderColor: "var(--border)" }}
        title={selected ? `Modelo: ${selected}` : "Seleccionar modelo"}
      >
        <Icon path={ICONS.sparkle} size={13} />
        <span className="truncate">{selected || "Modelo"}</span>
        {loading ? <Spinner size={11} /> : <Icon path={ICONS.chevronDown} size={12} />}
      </button>
      {open && (
        <div
          className="absolute bottom-full mb-2 left-0 w-72 max-h-72 overflow-y-auto rounded-xl border shadow-lg z-30"
          style={{ background: "var(--bg-panel)", borderColor: "var(--border)" }}
        >
          {!models && <p className="p-3 text-xs" style={{ color: "var(--text-dim)" }}>Cargando…</p>}
          {models?.error && (
            <p className="p-3 text-xs" style={{ color: "#ef4444" }}>
              {models.error} — el catálogo proviene del proveedor; nada inventado.
            </p>
          )}
          {models && models.models.length === 0 && !models.error && (
            <p className="p-3 text-xs" style={{ color: "var(--text-dim)" }}>
              El proveedor no devolvió modelos.
            </p>
          )}
          {models?.models.map((m) => (
            <button
              key={m.id}
              onClick={() => void select(m.id)}
              className="w-full text-left px-3 py-2 text-sm hover:bg-black/5 dark:hover:bg-white/10 flex items-center justify-between gap-2"
            >
              <span className="truncate">{m.id}</span>
              {m.id === selected && <Icon path={ICONS.check} size={14} className="shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
