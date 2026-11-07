"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE, setCsrf } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : `Error ${res.status}`);
        return;
      }
      setCsrf(data.csrf_token);
      router.replace("/");
    } catch {
      setError("No se pudo conectar con el backend");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-dvh flex items-center justify-center p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-2xl border p-6 flex flex-col gap-4"
        style={{ background: "var(--bg-panel)", borderColor: "var(--border)" }}
      >
        <div className="flex flex-col items-center gap-2 mb-2">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center text-white font-bold text-lg"
            style={{ background: "var(--accent)" }}
          >
            HJ
          </div>
          <h1 className="text-lg font-semibold">HacheCode Agent</h1>
          <p className="text-xs" style={{ color: "var(--text-dim)" }}>
            Panel web V4 · acceso privado
          </p>
        </div>
        <label className="text-sm flex flex-col gap-1">
          Usuario
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            className="rounded-lg border px-3 py-2 bg-transparent outline-none focus:ring-2"
            style={{ borderColor: "var(--border)" }}
          />
        </label>
        <label className="text-sm flex flex-col gap-1">
          Contraseña
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            className="rounded-lg border px-3 py-2 bg-transparent outline-none focus:ring-2"
            style={{ borderColor: "var(--border)" }}
          />
        </label>
        {error && (
          <p className="text-sm rounded-lg px-3 py-2" style={{ color: "#ef4444", background: "rgba(239,68,68,.08)" }}>
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg py-2.5 font-medium text-white disabled:opacity-50"
          style={{ background: "var(--accent)" }}
        >
          {busy ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </main>
  );
}
