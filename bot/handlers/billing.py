"""Saldo real, tokens, costes, presupuestos y alertas."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ..utils import esc, fmt_cost, send_long, trunc
from .helpers import provider_error_message

router = Router(name="billing")


@router.message(Command("balance"))
async def cmd_balance(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    try:
        provider = await ctx.providers.get(uid)
    except Exception as e:
        await message.answer(provider_error_message(e))
        return
    pname = await ctx.providers.active_name(uid)
    from core.billing.balance import fetch_balance_summary
    info = await fetch_balance_summary(provider)
    if not info.get("available"):
        await message.answer(f"💳 Saldo <b>{esc(pname)}</b>: NO DISPONIBLE\n"
                             f"Motivo: {esc(info.get('reason', ''))}")
        return
    lines = [f"💳 <b>Saldo real de {esc(pname)}</b>",
             f"Total: <b>{info['total']:.2f} {info.get('currency', '')}</b>"]
    if info.get("granted") is not None:
        lines.append(f"Otorgado: {info['granted']:.2f}")
    if info.get("topped_up") is not None:
        lines.append(f"Recargado: {info['topped_up']:.2f}")
    lines.append("Disponible: " + ("✅ sí" if info.get("is_available") else "⛔ no (is_available=false)"))
    await message.answer("\n".join(lines))


@router.message(Command("tokens"))
async def cmd_tokens(message: Message, ctx):
    uid = message.from_user.id
    from core.billing.period import month_start, today_start
    t_all = await ctx.usage.totals(uid)
    t_day = await ctx.usage.totals(uid, since=today_start())
    t_month = await ctx.usage.totals(uid, since=month_start())
    await message.answer(
        "<b>🎯 Tokens</b>\n"
        f"Hoy: in {t_day['pt']:,} · out {t_day['ct']:,} · total {t_day['tt']:,}\n"
        f"Mes: in {t_month['pt']:,} · out {t_month['ct']:,} · total {t_month['tt']:,}\n"
        f"Histórico: in {t_all['pt']:,} · out {t_all['ct']:,} · total {t_all['tt']:,} "
        f"({t_all['calls']} llamadas)")


@router.message(Command("usage"))
async def cmd_usage(message: Message, ctx):
    uid = message.from_user.id
    from core.billing.period import month_start
    rows = await ctx.usage.by_model(uid, since=month_start())
    if not rows:
        await message.answer("Sin consumo registrado este mes.")
        return
    lines = ["<b>📈 Consumo por modelo (mes)</b>"]
    for r in rows:
        lines.append(f"• {esc(r['provider'])}/{esc(r['model'])}: {r['calls']} llamadas · "
                     f"{r['tt']:,} tokens · {fmt_cost(r['cost'] if r['cost'] else None)}")
    conv_id = await ctx.store.get_pref(uid, "active_conversation")
    proj = await ctx.projects.active(uid)
    if conv_id:
        t = await ctx.usage.totals(uid, conversation_id=int(conv_id))
        lines.append(f"\nConversación activa: {t['tt']:,} tokens · {fmt_cost(t['cost'] or None)}")
    if proj:
        t = await ctx.usage.totals(uid, project_id=proj["id"])
        lines.append(f"Proyecto '{esc(proj['name'])}': {t['tt']:,} tokens · {fmt_cost(t['cost'] or None)}")
    await send_long(message, "\n".join(lines))


@router.message(Command("cost"))
async def cmd_cost(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    from core.billing.period import month_start, today_start
    arg = (command.args or "").strip().lower() if command else ""
    if arg == "today":
        t = await ctx.usage.totals(uid, since=today_start())
        await message.answer(f"💸 Coste de HOY: <b>{fmt_cost(t['cost'] if t['calls'] else None)}</b> "
                             f"({t['tt']:,} tokens)")
        return
    if arg == "month":
        t = await ctx.usage.totals(uid, since=month_start())
        await message.answer(f"💸 Coste del MES: <b>{fmt_cost(t['cost'] if t['calls'] else None)}</b> "
                             f"({t['tt']:,} tokens)")
        return
    t_all = await ctx.usage.totals(uid)
    t_day = await ctx.usage.totals(uid, since=today_start())
    t_month = await ctx.usage.totals(uid, since=month_start())
    note = ("Costes ESTIMADOS con las tarifas configuradas (/price set). "
            "Si no hay tarifa para un modelo, su coste no se cuenta.")
    await message.answer(
        "<b>💸 Costes</b>\n"
        f"Hoy: {fmt_cost(t_day['cost'] if t_day['calls'] else None)}\n"
        f"Mes: {fmt_cost(t_month['cost'] if t_month['calls'] else None)}\n"
        f"Histórico: {fmt_cost(t_all['cost'] if t_all['calls'] else None)}\n\n"
        f"<i>{note}</i>")


@router.message(Command("price"))
async def cmd_price(message: Message, ctx, command: CommandObject = None):
    """Configura tarifas por 1M de tokens: /price set modelo in out [moneda] [cache_hit]"""
    uid = message.from_user.id
    if not command or not command.args:
        rates = await ctx.store.list_rates()
        lines = ["<b>🏷 Tarifas configuradas</b> (por 1M tokens)"]
        for r in rates:
            lines.append(f"• {esc(r['provider'])}/{esc(r['model'])}: in {r['input_per_mtok']} · "
                         f"out {r['output_per_mtok']} {r['currency']}")
        lines.append("\nUso: /price set &lt;modelo&gt; &lt;in&gt; &lt;out&gt; [moneda] [cache_hit]")
        await message.answer("\n".join(lines))
        return
    parts = command.args.split()
    if parts[0].lower() != "set" or len(parts) < 4:
        await message.answer("Uso: /price set &lt;modelo&gt; &lt;in&gt; &lt;out&gt; [moneda] [cache_hit]")
        return
    model, in_p, out_p = parts[1], parts[2], parts[3]
    currency = parts[4].upper() if len(parts) > 4 else "USD"
    cache = parts[5] if len(parts) > 5 else None
    try:
        in_f, out_f = float(in_p), float(out_p)
        cache_f = float(cache) if cache else None
    except ValueError:
        await message.answer("Precios inválidos.")
        return
    pname = await ctx.providers.active_name(uid)
    await ctx.pricing.set_rate(pname, model, in_f, out_f, currency, cache_f)
    await message.answer(f"✔️ Tarifa {esc(pname)}/{esc(model)}: in {in_f} · out {out_f} · "
                         f"cache {cache_f or '-'} {currency} (por 1M)")


@router.message(Command("limits"))
async def cmd_limits(message: Message, ctx):
    uid = message.from_user.id
    b = await ctx.store.get_budget(uid)
    s = ctx.settings
    await message.answer(
        "<b>🚧 Límites</b>\n"
        f"• Presupuesto por tarea: {b.get('per_task') or 'sin límite'}\n"
        f"• Presupuesto diario: {b.get('per_day') or 'sin límite'}\n"
        f"• Pasos máximos por tarea: {s.max_task_steps}\n"
        f"• Tareas concurrentes: {s.max_concurrent_tasks} (1 por usuario)\n"
        f"• Sandbox: {s.sandbox_memory_mb} MB · {s.sandbox_cpus} CPU · {s.sandbox_pids} pids · "
        f"timeout {s.sandbox_timeout_s}s\n"
        f"• Subidas: {s.max_file_mb} MB por archivo · ZIP hasta {s.max_zip_unpacked_mb} MB")


@router.message(Command("budget"))
async def cmd_budget(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    if not command or not command.args:
        b = await ctx.store.get_budget(uid)
        await message.answer(f"💰 <b>Presupuesto</b>\nPor tarea: {b.get('per_task') or 'sin límite'}\n"
                             f"Por día: {b.get('per_day') or 'sin límite'}\n\n"
                             "Uso: /budget task &lt;monto&gt; · /budget day &lt;monto&gt; · /budget off")
        return
    parts = command.args.split()
    try:
        if parts[0] == "task":
            await ctx.store.set_budget(uid, per_task=float(parts[1]))
            await message.answer(f"✔️ Presupuesto por tarea: {parts[1]}")
        elif parts[0] == "day":
            await ctx.store.set_budget(uid, per_day=float(parts[1]))
            await message.answer(f"✔️ Presupuesto diario: {parts[1]}")
        elif parts[0] == "off":
            await ctx.store.set_budget(uid, per_task=None, per_day=None)
            await message.answer("Presupuestos desactivados.")
        else:
            raise ValueError
    except (ValueError, IndexError):
        await message.answer("Uso: /budget task &lt;monto&gt; · /budget day &lt;monto&gt; · /budget off")


@router.message(Command("alerts"))
async def cmd_alerts(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    if not command or not command.args:
        b = await ctx.store.get_budget(uid)
        await message.answer(
            "🔔 <b>Alertas</b>\n"
            f"Saldo bajo: {b.get('alert_balance') or 'desactivada'}\n"
            f"Coste diario máximo: {b.get('alert_daily') or 'desactivada'}\n\n"
            "Uso: /alerts balance &lt;monto&gt; · /alerts daily &lt;monto&gt; · /alerts off")
        return
    parts = command.args.split()
    try:
        if parts[0] == "balance":
            await ctx.store.set_budget(uid, alert_balance=float(parts[1]))
            await message.answer(f"✔️ Alerta de saldo bajo: {parts[1]} (se comprueba con /balance)")
        elif parts[0] == "daily":
            await ctx.store.set_budget(uid, alert_daily=float(parts[1]))
            await message.answer(f"✔️ Alerta de coste diario: {parts[1]}")
        elif parts[0] == "off":
            await ctx.store.set_budget(uid, alert_balance=None, alert_daily=None)
            await message.answer("Alertas desactivadas.")
        else:
            raise ValueError
    except (ValueError, IndexError):
        await message.answer("Uso: /alerts balance &lt;monto&gt; · /alerts daily &lt;monto&gt; · /alerts off")


async def send_stats(message: Message, ctx, uid: int | None = None):
    uid = uid or message.from_user.id
    from core.billing.period import month_start
    t_all = await ctx.usage.totals(uid)
    t_month = await ctx.usage.totals(uid, since=month_start())
    projects = await ctx.projects.list(uid)
    tasks = await ctx.store.list_tasks(uid, limit=100)
    chats = await ctx.store.list_conversations(uid, limit=100)
    done = sum(1 for t in tasks if t["status"] == "done")
    failed = sum(1 for t in tasks if t["status"] == "failed")
    await message.answer(
        "<b>📊 Estadísticas</b>\n"
        f"Proyectos: {len(projects)} · Conversaciones: {len(chats)}\n"
        f"Tareas: {len(tasks)} (✅ {done} · ❌ {failed})\n"
        f"Llamadas al modelo: {t_all['calls']} ({t_month['calls']} este mes)\n"
        f"Tokens totales: {t_all['tt']:,}\n"
        f"Coste total: {fmt_cost(t_all['cost'] if t_all['calls'] else None)}\n"
        f"Uptime del bot: {ctx.uptime_s() // 60} min")


@router.message(Command("stats"))
async def cmd_stats(message: Message, ctx):
    await send_stats(message, ctx)


# --------- comprobacion de alertas tras registrar consumo -------------------


async def check_alerts_after_usage(ctx, user_id: int, chat_id: int, cost, provider_name: str):
    if cost is None:
        return
    b = await ctx.store.get_budget(user_id)
    if b.get("alert_daily"):
        day = await ctx.usage.day_cost(user_id)
        if day >= float(b["alert_daily"]):
            try:
                await ctx.bot.send_message(
                    chat_id, f"🔔 ALERTA: coste diario {day:.2f} >= {b['alert_daily']}")
            except Exception:
                pass
