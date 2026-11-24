"""Etapa 1 do experimento: seleção por regra a partir do catálogo e custo estimado, sem chamadas pagas."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cardfactory.benchmark import experiment as ex

NOW = datetime(2026, 11, 24, tzinfo=UTC)


def _row(mid, pin, pout, *, days=30, ctx=200_000, params=("structured_outputs", "reasoning")):
    return {"model_id": mid, "name": mid, "pricing": {"prompt": pin, "completion": pout}, "context_length": ctx,
            "supported_parameters": list(params), "raw": {"created": (NOW - timedelta(days=days)).timestamp()}}


ROWS = [
    _row("openai/a-new", "0.000002", "0.000010", days=10),
    _row("openai/a-old", "0.000001", "0.000004", days=200),
    _row("openai/a-huge", "0.00002", "0.00008", days=5),  # acima do teto
    _row("anthropic/b", "0.000003", "0.000015"),
    _row("google/c", "0.0000003", "0.0000025", params=("response_format",)),
    _row("deepseek/d", "0.0000003", "0.0000012", params=("structured_outputs",)),
    _row("qwen/e:free", "0", "0"),  # gratuito: excluído
    _row("qwen/e-vl", "0.0000002", "0.000001"),  # visão: excluído
    _row("z-ai/f", "0.0000006", "0.0000022", params=("tools",)),  # sem saída estruturada
    _row("moonshotai/g", "0.0000006", "0.0000025", ctx=32_000),  # contexto curto
    _row("minimax/h", "0.0000003", "0.0000012", days=900),  # antigo
    _row("meta-llama/i", "0.0000001", "0.0000003"),  # fora das famílias
]


def test_selection_is_rule_based_and_filters():
    sel = {c.family: c for c in ex.select(ROWS, Decimal("16"), NOW)}
    assert set(sel) == {"OpenAI", "Anthropic", "Google", "DeepSeek"}
    assert sel["OpenAI"].model_id == "openai/a-new"  # mais recente dentro do teto
    assert "openai/a-huge" in sel["OpenAI"].alternatives
    assert not sel["DeepSeek"].reasoning and sel["OpenAI"].reasoning


def test_plan_estimates_cost_in_brl_and_checks_budget():
    p = ex.plan(ROWS, budget_brl=Decimal("15"), fx_rate=Decimal("5.40"), fx_margin=Decimal("0.10"), now=NOW)
    assert p["missing_families"] == ["GLM", "Qwen", "Kimi", "MiniMax"]
    assert p["fixed_auditor"] in {c["model_id"] for c in p["auditors"]}
    total = sum(Decimal(r["usd"]) for r in p["rounds"].values())
    assert abs(total - Decimal(p["total"]["usd"])) < Decimal("0.001")
    assert Decimal(p["total"]["brl"]) > Decimal(p["total"]["usd"]) * 5
    assert isinstance(p["fits"], bool)
    md = ex.to_markdown(p)
    assert "openai/a-new" in md and "Rodada A" in md


def test_reasoning_output_is_charged_with_factor():
    c = ex.Candidate("X", "x/y", "y", Decimal("1"), Decimal("10"), 100_000, True, None)
    assert c.cost_usd(1_000_000, 1_000_000) == Decimal("1") + Decimal("10") * ex.REASONING_FACTOR


def test_plan_without_fx_reports_usd_only():
    p = ex.plan(ROWS, budget_brl=Decimal("15"), fx_rate=None, fx_margin=Decimal("0.10"), now=NOW)
    assert p["total"]["brl"] is None and p["fits"] is None
    assert "sem câmbio" in ex.to_markdown(p)
