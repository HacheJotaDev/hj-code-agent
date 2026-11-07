"use client";

/** Suscripción SSE a una tarea con reconexión automática.
 *
 * EventSource reenvía Last-Event-ID al reconectar (cierre de portátil, cambio
 * de red) y el backend reproduce el historial desde ese punto: nunca se pierde
 * progreso. Devuelve los eventos en orden y un flag de conexión.
 */
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "./api";
import type { TaskEvent } from "./types";

export function useTaskStream(taskId: number | null, onEvent: (ev: TaskEvent) => void) {
  const [connected, setConnected] = useState(false);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!taskId || typeof window === "undefined") return;
    let es: EventSource | null = null;
    let closed = false;

    const connect = () => {
      if (closed) return;
      es = new EventSource(`${API_BASE}/tasks/${taskId}/stream`);
      es.onopen = () => setConnected(true);
      const types = ["plan", "tool", "notify", "status", "plan_incomplete", "end"];
      for (const t of types) {
        es.addEventListener(t, (e: MessageEvent<string>) => {
          try {
            const data = JSON.parse(e.data || "{}") as Record<string, unknown>;
            const idNum = e.lastEventId ? Number(e.lastEventId) : 0;
            handlerRef.current({
              id: idNum,
              task_id: taskId,
              type: t,
              data,
              created_at: new Date().toISOString(),
            });
          } catch {
            /* evento malformado: ignorar */
          }
        });
      }
      es.onerror = () => {
        setConnected(false);
        // EventSource reconecta solo; si la tarea ya terminó el backend
        // envió `end` y cerramos por nuestra cuenta vía onEvent('end').
      };
    };
    connect();
    return () => {
      closed = true;
      es?.close();
      setConnected(false);
    };
  }, [taskId]);

  return connected;
}
