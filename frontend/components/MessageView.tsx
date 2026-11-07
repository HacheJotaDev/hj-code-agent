"use client";

/** Vista de mensajes: Markdown real, bloques de código resaltados y filas de
 * llamadas a herramientas (colapsables, con evidencia). */
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import type { ChatMessage } from "@/lib/types";
import { ICONS, Icon, Spinner } from "./ui";

function ToolRow({ msg }: { msg: ChatMessage }) {
  const [open, setOpen] = useState(false);
  let pretty = msg.content || "";
  let name = msg.name || "herramienta";
  let ok = true;
  try {
    const parsed = JSON.parse(pretty);
    if (typeof parsed === "object" && parsed !== null) {
      ok = parsed.ok !== false;
      name = msg.name || name;
      pretty = typeof parsed.result === "string" ? parsed.result : JSON.stringify(parsed.result ?? parsed, null, 2);
    }
  } catch { /* texto plano */ }
  return (
    <div className="my-1 rounded-lg border text-xs" style={{ borderColor: "var(--border)" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left"
        style={{ color: ok ? "var(--text-dim)" : "#ef4444" }}
      >
        <Icon path={ok ? ICONS.chevron : ICONS.alert} size={12} />
        <span className="font-medium" style={{ color: "var(--text)" }}>
          {name === "update_plan" ? "Actualizó el plan" : `Herramienta: ${name}`}
        </span>
        <span className="truncate flex-1" style={{ color: "var(--text-dim)" }}>
          {pretty.split("\n")[0]?.slice(0, 90)}
        </span>
        <Icon path={ICONS.chevronDown} size={12} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <pre className="px-3 py-2 overflow-x-auto border-t text-[11px] leading-relaxed" style={{ borderColor: "var(--border)", background: "var(--bg-sidebar)" }}>
          {pretty.slice(0, 6000)}
        </pre>
      )}
    </div>
  );
}

export default function MessageView({
  messages,
  running,
}: {
  messages: ChatMessage[];
  running: boolean;
}) {
  return (
    <div className="flex flex-col gap-3">
      {messages.map((m) => {
        if (m.role === "tool") return <ToolRow key={m.id} msg={m} />;
        const isUser = m.role === "user";
        return (
          <div key={m.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[92%] sm:max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm ${
                isUser ? "text-white rounded-br-md" : "rounded-bl-md"
              }`}
              style={
                isUser
                  ? { background: "var(--accent)" }
                  : { background: "var(--bg-panel)", border: "1px solid var(--border)" }
              }
            >
              {isUser ? (
                <p className="whitespace-pre-wrap break-words">{m.content}</p>
              ) : (
                <>
                  {m.tool_calls && m.tool_calls.length > 0 && (
                    <div className="mb-1 flex items-center gap-1.5 text-xs" style={{ color: "var(--text-dim)" }}>
                      <Icon path={ICONS.code} size={12} />
                      {m.tool_calls.length} llamada(s) a herramientas
                    </div>
                  )}
                  <div className="md-body">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      rehypePlugins={[[rehypeHighlight, { detect: false, ignoreMissing: true }]]}
                    >
                      {m.content || ""}
                    </ReactMarkdown>
                  </div>
                  {m.tokens_out ? (
                    <p className="mt-1.5 text-[10px]" style={{ color: "var(--text-dim)" }}>
                      {m.tokens_in || 0}→{m.tokens_out} tokens{m.cost ? ` · $${Number(m.cost).toFixed(4)}` : ""}
                    </p>
                  ) : null}
                </>
              )}
            </div>
          </div>
        );
      })}
      {running && (
        <div className="flex items-center gap-2 text-xs px-2" style={{ color: "var(--text-dim)" }}>
          <Spinner /> El agente está trabajando…
        </div>
      )}
    </div>
  );
}
