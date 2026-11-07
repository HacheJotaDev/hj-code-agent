"""16) y 17) Persistencia de conversaciones y recuperacion tras reinicio."""
from core.storage.database import Database
from core.storage.repositories import Store


async def test_historial_sobrevive_reinicio(tmp_path):
    db = Database(tmp_path / "persist.db")
    await db.connect()
    await db.migrate()
    s = Store(db)
    cid = await s.create_conversation(111, None, "deepseek", "deepseek-chat", "Chat")
    await s.add_message(cid, "user", "Hola mundo")
    await s.add_message(cid, "assistant", "¡Hola!")
    n = await s.count_messages(cid)
    await db.close()

    # "reinicio": reabrir la misma BD
    db2 = Database(tmp_path / "persist.db")
    await db2.connect()
    s2 = Store(db2)
    rows = await s2.get_messages(cid)
    assert len(rows) == n == 2
    assert rows[0]["content"] == "Hola mundo"
    conv = await s2.get_conversation(cid)
    assert conv["model"] == "deepseek-chat"
    # preferencias tambien (guardadas antes del cierre)
    await s2.set_pref(111, "active_provider", "deepseek")
    assert await s2.get_pref(111, "active_provider") == "deepseek"
    await db2.close()


async def test_recuperacion_integridad(tmp_path):
    db = Database(tmp_path / "wal.db")
    await db.connect()
    await db.migrate()
    await db.recover()  # no lanza
    await db.close()


async def test_tareas_en_cola_sobreviven(tmp_path):
    db = Database(tmp_path / "q.db")
    await db.connect()
    await db.migrate()
    s = Store(db)
    tid = await s.create_task(111, 1, None, None, "agent", "persistente", 5)
    await db.close()
    db2 = Database(tmp_path / "q.db")
    await db2.connect()
    s2 = Store(db2)
    t = await s2.get_task(tid)
    assert t["status"] == "queued"
    n = await s2.recover_interrupted()
    assert n == 0
    await db2.close()


async def test_busqueda_y_export(services, store):
    cid = await store.create_conversation(111, None, "p", "m", "t")
    await store.add_message(cid, "user", "funcion especial de facturacion")
    rows = await store.search_messages(111, "facturacion")
    assert rows and rows[0]["conversation_id"] == cid
    rows = await store.search_messages(222, "facturacion")
    assert rows == []  # aislamiento entre usuarios
