"""7) y 8) Registro de tokens y calculo de costes."""
from core.providers.base import Usage


async def test_record_usage_y_totales(services, store):
    await services.pricing.set_rate("deepseek", "deepseek-chat", 0.27, 1.10, "USD")
    u1 = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000)
    cost = await services.usage.record(111, "deepseek", "deepseek-chat", u1)
    assert abs(cost - (0.27 + 1.10)) < 1e-9  # 1M tokens de cada tipo

    u2 = Usage(prompt_tokens=500, completion_tokens=100, total_tokens=600)
    cost2 = await services.usage.record(111, "deepseek", "deepseek-chat", u2,
                                        conversation_id=1)
    assert abs(cost2 - (500 * 0.27 + 100 * 1.10) / 1e6) < 1e-9

    t = await services.usage.totals(111)
    assert t["calls"] == 2 and t["tt"] == 2_000_600
    assert 1.36 < t["cost"] < 1.38


async def test_coste_con_cache_hit_deepseek(services):
    await services.pricing.set_rate("deepseek", "m", 0.27, 1.10, "USD", cache_hit_per_mtok=0.07)
    u = Usage(prompt_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000,
              details={"prompt_cache_hit_tokens": 800_000, "prompt_cache_miss_tokens": 200_000})
    cost, cur = await services.pricing.estimate("deepseek", "m", u)
    esperado = (200_000 * 0.27 + 800_000 * 0.07) / 1e6
    assert abs(cost - esperado) < 1e-9 and cur == "USD"


async def test_sin_tarifa_coste_none_no_inventa(services):
    cost = await services.usage.record(111, "deepseek", "modelo-desconocido",
                                       Usage(10, 5, 15))
    assert cost is None
    t = await services.usage.totals(111)
    assert t["cost"] == 0 and t["tt"] == 15


async def test_usage_por_modelo_y_dia(services):
    await services.pricing.set_rate("deepseek", "a", 1, 1)
    await services.usage.record(111, "deepseek", "a", Usage(100, 50, 150))
    await services.usage.record(111, "deepseek", "a", Usage(10, 5, 15))
    rows = await services.usage.by_model(111)
    assert rows[0]["model"] == "a" and rows[0]["calls"] == 2 and rows[0]["tt"] == 165
    days = await services.usage.by_day(111)
    assert len(days) == 1 and days[0]["tt"] == 165
