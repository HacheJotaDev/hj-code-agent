# Despliegue del FRONTEND en Vercel (V4)

El frontend es Next.js estático + proxy `/api/*`. Vercel NO ejecuta Python,
DeepSeek, workers ni sandboxes: solo sirve la UI y reescribe `/api/*` al
backend del VPS.

## Paso 1 — Repositorio

1. La rama `feature/hachecode-web-v4` debe estar publicada en GitHub
   (pendiente de tu autorización de push).
2. En Vercel: **Add New → Project → Import** `HacheJotaDev/hj-code-agent`.
3. **Root Directory**: `frontend`.

## Paso 2 — Variables de entorno (Project Settings → Environment Variables)

| Variable | Valor | Notas |
|---|---|---|
| `HACHE_API_ORIGIN` | `https://api.TUDOMINIO.com` | Origen del backend en el VPS. NUNCA una IP cruda sin TLS. |
| `NEXT_PUBLIC_API_BASE` | `/api` | El navegador siempre habla con su propio origen (proxy). |

No hay IPs ni dominios fijos en el código: todo va por estas variables.

## Paso 3 — HTTPS del backend (obligatorio)

Vercel reescribe `/api/*` a `HACHE_API_ORIGIN`. Para TLS válido en el VPS
(sin desactivar verificación, sin HTTP público):

**Opción recomendada — Caddy en el VPS** (certificado automático):

```caddy
# /etc/caddy/Caddyfile (subdominio dedicado, p. ej. api.tudominio.com)
api.tudominio.com {
    reverse_proxy 127.0.0.1:8900
}
```

`sudo systemctl reload caddy` y usa `https://api.tudominio.com` como
`HACHE_API_ORIGIN`. Caddy solo proxya al servicio web V4; no toca el bot.

> Si solo tienes la IP de Contabo: no hay CA pública que emita certificado
> para IP sin validación compleja. Lo correcto es un dominio → A record →
> IP del VPS → Caddy. No se desactiva la verificación TLS en ningún caso.

## Paso 4 — Deploy

- **Deploy** y espera el build (`npm run build` en `frontend/`).
- Verifica: `https://tu-web.vercel.app/login` carga y el login autentica
  contra tu VPS (la petición visible en la pestaña Network es a tu propio
  origen, `/api/auth/login`, y Vercel la reenvía por HTTPS).

## Notas

- SSE funciona en Vercel (streaming de rewrites). El `EventSource` reconecta
  solo y el backend reproduce el historial desde `Last-Event-ID`.
- No pongas secretos en el frontend: no los necesita (todo el poder está en
  las cookies de sesión del backend).
- Actualización: push a la rama → Vercel redespliega; el backend es inmune.
