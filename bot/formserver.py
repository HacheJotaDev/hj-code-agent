"""Formulario HTTPS-temporal de un solo uso para API keys (nunca por chat).

Sirve en 127.0.0.1:<puerto> del VPS. Para usarlo desde el PC del admin:
    ssh -L <puerto>:127.0.0.1:<puerto> vps
El token de un solo uso expira en 10 minutos y se destruye al usarse.
Si se configura HJ_FORM_BASE_URL puede publicarse tras un proxy HTTPS.
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

log = logging.getLogger(__name__)

PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>HJ Code Agent - Clave segura</title>
<style>body{{font-family:system-ui;max-width:560px;margin:8vh auto;padding:0 16px}}
input,select{{width:100%;padding:10px;margin:6px 0 16px;box-sizing:border-box}}
button{{background:#0b7;font-size:16px;padding:10px 22px;border:0;border-radius:8px;color:#fff}}
.small{{color:#666;font-size:13px}}</style></head><body>
<h2>HJ Code Agent V2 — {title}</h2>
<p>{intro}</p>
<form method="post" action="/set/{token}">
<label>Clave / token</label>
<input type="password" name="secret" required autocomplete="off" minlength="8">
<button type="submit">Guardar cifrado</button>
</form>
<p class="small">Página de un solo uso (expira en 10 min). Se sirve solo por loopback.
El valor se guarda cifrado con la clave maestra y nunca se vuelve a mostrar.</p>
</body></html>"""

OK_PAGE = "<!doctype html><html lang='es'><meta charset='utf-8'><body style='font-family:system-ui'>" \
          "<h2>✅ Clave guardada y cifrada</h2><p>Puedes cerrar esta página y volver a Telegram.</p></body></html>"


def build_form_app(ctx) -> web.Application:
    app = web.Application()
    vault = ctx.vault

    async def health(_):
        return web.json_response({"ok": True})

    async def form_get(request):
        token = request.match_info["token"]
        data = await ctx.store.kv_get(f"form:{token}")
        if not data:
            return web.Response(status=410, text="Enlace expirado o ya utilizado.")
        kind = data.get("kind")
        title = "Conexión segura de GitHub" if kind == "github_token" else \
            f"API key de {data.get('provider', '')}"
        intro = ("Pega tu token fine-grained de GitHub (permisos mínimos)."
                 if kind == "github_token" else
                 "Pega la API key del proveedor. Se cifrará antes de guardarse.")
        return web.Response(text=PAGE.format(token=token, title=title, intro=intro),
                            content_type="text/html")

    async def form_post(request):
        token = request.match_info["token"]
        data = await ctx.store.kv_get(f"form:{token}")
        if not data:
            return web.Response(status=410, text="Enlace expirado o ya utilizado.")
        form = await request.post()
        secret = (form.get("secret") or "").strip()
        if not secret or vault is None:
            return web.Response(status=400, text="Clave vacía o bóveda no configurada.")
        kind = data.get("kind")
        provider = "github" if kind == "github_token" else data.get("provider")
        user_id = int(data.get("user_id") or 0)
        await ctx.store.set_credential(user_id, provider, vault.encrypt(secret))
        await ctx.store.kv_del(f"form:{token}")  # un solo uso
        await ctx.store.audit(user_id, "credential.set", f"{provider} (via formulario)")
        log.info("Credencial guardada para proveedor %s (user %s)", provider, user_id)
        return web.Response(text=OK_PAGE, content_type="text/html")

    app.router.add_get("/health", health)
    app.router.add_get("/set/{token}", form_get)
    app.router.add_post("/set/{token}", form_post)
    return app


async def start_form_server(ctx) -> web.AppRunner:
    runner = web.AppRunner(build_form_app(ctx))
    await runner.setup()
    site = web.TCPSite(runner, host=ctx.settings.form_host, port=ctx.settings.form_port)
    try:
        await site.start()
        log.info("Formulario seguro en %s:%s", ctx.settings.form_host, ctx.settings.form_port)
        return runner
    except OSError as e:
        log.warning("No se pudo iniciar el formulario en %s:%s (%s); /setapi sin formulario",
                    ctx.settings.form_host, ctx.settings.form_port, e)
        await runner.cleanup()
        return None
