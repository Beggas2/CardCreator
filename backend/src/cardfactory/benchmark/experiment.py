"""Etapa 1 do experimento (BENCHMARK_PROTOCOL §5): seleção de candidatos e custo estimado, sem chamadas pagas.

A seleção parte só do catálogo sincronizado. Nenhum ID de modelo é escrito aqui: as famílias são reconhecidas
pelo prefixo do provedor no ID do catálogo, e o modelo de cada família é escolhido por regra (mais recente que
passa nos filtros e cabe no teto de preço). O resultado é uma proposta para a proprietária aprovar.

As estimativas de tokens são conservadoras e declaradas em `ASSUMPTIONS`. Modelos com raciocínio cobram os
tokens de raciocínio como saída; por isso a saída deles é multiplicada por `REASONING_FACTOR`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from cardfactory.finance.money import usd_to_brl

FAMILIES: dict[str, tuple[str, ...]] = {
    "OpenAI": ("openai/",), "Anthropic": ("anthropic/",), "Google": ("google/",), "DeepSeek": ("deepseek/",),
    "GLM": ("z-ai/", "thudm/"), "Qwen": ("qwen/",), "Kimi": ("moonshotai/",), "MiniMax": ("minimax/",),
}
EXCLUDE_WORDS = ("image", "audio", "tts", "embed", "guard", "search", "vision", "-vl", "realtime", "codex", "coder",
                 "-code", "legal", "omni", "banana", "customtools", "preview", "nano", "lite")
MIN_CONTEXT = 64_000
MAX_AGE_DAYS = 540
FRESH_WINDOW_DAYS = 120  # dentro da família, só a geração recente concorre
REASONING_FACTOR = Decimal("2")
MILLION = Decimal(1_000_000)

# Tetos de preço por papel (USD por milhão de tokens de saída). Configuráveis na chamada.
DEFAULT_CAPS_USD = {"creator": Decimal("16"), "auditor_scientific": Decimal("16")}

# Tokens estimados por chamada (entrada, saída sem raciocínio). Medidos sobre os prompts compostos atuais
# (criador ≈ 3,1 mil tokens; auditores ≈ 1,6–2,2 mil) mais o contexto de fontes e os cards.
ASSUMPTIONS: dict[str, Any] = {
    "round_a": {"objectives": 5, "creator_calls": 1, "creator_in": 16_000, "creator_out": 14_000,
                "audit_calls": 2, "audit_in": 12_000, "audit_out": 5_000},
    "round_b": {"items_dev": 12, "calls": 2, "in": 14_000, "out": 6_000, "auditors": 3},
    "round_c": {"objectives": 12, "pipelines": 2, "gen_calls": 3, "gen_in": 16_000, "gen_out": 14_000,
                "audit_calls": 8, "audit_in": 12_000, "audit_out": 5_000, "correction_calls": 2,
                "correction_in": 10_000, "correction_out": 6_000},
    "research_shared": {"calls": 4, "in": 20_000, "out": 6_000},
}


@dataclass
class Candidate:
    family: str
    model_id: str
    name: str
    prompt_usd_m: Decimal
    completion_usd_m: Decimal
    context_length: int | None
    reasoning: bool
    created: datetime | None
    alternatives: list[str] = field(default_factory=list)

    def cost_usd(self, tokens_in: int, tokens_out: int) -> Decimal:
        out = Decimal(tokens_out) * (REASONING_FACTOR if self.reasoning else 1)
        return (Decimal(tokens_in) * self.prompt_usd_m + out * self.completion_usd_m) / MILLION

    def as_dict(self) -> dict[str, Any]:
        return {"family": self.family, "model_id": self.model_id, "name": self.name,
                "prompt_usd_m": _s(self.prompt_usd_m), "completion_usd_m": _s(self.completion_usd_m),
                "context_length": self.context_length, "reasoning": self.reasoning,
                "created": self.created.date().isoformat() if self.created else None,
                "alternatives": self.alternatives}


def _s(d: Decimal) -> str:
    return format(d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize(), "f")


def _price(pricing: dict[str, Any], key: str) -> Decimal | None:
    try:
        v = Decimal(str(pricing.get(key)))
    except Exception:  # noqa: BLE001 - preço ausente ou não numérico
        return None
    return v * MILLION if v > 0 else None


def _family(model_id: str) -> str | None:
    return next((f for f, prefixes in FAMILIES.items() if model_id.startswith(prefixes)), None)


def eligible(row: dict[str, Any], now: datetime) -> Candidate | None:
    mid = row["model_id"]
    fam = _family(mid)
    params = set(row.get("supported_parameters") or [])
    if fam is None or ":" in mid or any(w in mid.lower() for w in EXCLUDE_WORDS):
        return None
    if not params & {"structured_outputs", "response_format"}:
        return None
    if (row.get("context_length") or 0) < MIN_CONTEXT:
        return None
    pin, pout = _price(row.get("pricing") or {}, "prompt"), _price(row.get("pricing") or {}, "completion")
    if pin is None or pout is None:
        return None
    created_ts = (row.get("raw") or {}).get("created")
    created = datetime.fromtimestamp(created_ts, UTC) if isinstance(created_ts, (int, float)) else None
    if created and now - created > timedelta(days=MAX_AGE_DAYS):
        return None
    return Candidate(fam, mid, row.get("name") or mid, pin, pout, row.get("context_length"),
                     bool(params & {"reasoning", "include_reasoning"}), created)


def select(rows: list[dict[str, Any]], cap_usd_m: Decimal, now: datetime | None = None) -> list[Candidate]:
    """Um candidato por família.

    Concorrem os modelos de uso geral lançados até `FRESH_WINDOW_DAYS` antes do mais novo da família e dentro do
    teto. Entre eles vence o de maior preço de saída (o catálogo não informa qualidade; o preço é o indicador
    disponível de que é o modelo principal da geração, não a versão reduzida). Empate: o mais recente.
    """
    now = now or datetime.now(UTC)
    by_family: dict[str, list[Candidate]] = {}
    for row in rows:
        c = eligible(row, now)
        if c:
            by_family.setdefault(c.family, []).append(c)
    oldest = datetime.min.replace(tzinfo=UTC)
    out = []
    for fam in FAMILIES:
        pool = by_family.get(fam, [])
        newest = max((c.created or oldest for c in pool), default=oldest)
        fresh = [c for c in pool if (c.created or oldest) >= newest - timedelta(days=FRESH_WINDOW_DAYS)]
        within = sorted((c for c in fresh if c.completion_usd_m <= cap_usd_m),
                        key=lambda c: (c.completion_usd_m, c.created or oldest), reverse=True)
        if not within:
            continue
        pick = within[0]
        pick.alternatives = [c.model_id for c in sorted(fresh, key=lambda c: c.created or oldest, reverse=True)
                             if c is not pick][:4]
        out.append(pick)
    return out


def estimate(creators: list[Candidate], auditors: list[Candidate], fixed_auditor: Candidate | None,
             researcher: Candidate | None) -> dict[str, Decimal]:
    a, b, c, r = (ASSUMPTIONS[k] for k in ("round_a", "round_b", "round_c", "research_shared"))
    research = researcher.cost_usd(r["in"], r["out"]) * r["calls"] if researcher else Decimal(0)
    round_a = sum((k.cost_usd(a["creator_in"], a["creator_out"]) * a["creator_calls"] for k in creators), Decimal(0))
    if fixed_auditor:
        round_a += fixed_auditor.cost_usd(a["audit_in"], a["audit_out"]) * a["audit_calls"] * len(creators)
    ranked = sorted(auditors, key=lambda x: x.completion_usd_m, reverse=True)[: b["auditors"]]
    round_b = sum((k.cost_usd(b["in"], b["out"]) * b["calls"] for k in ranked), Decimal(0))
    # Rodada C: estimada com o criador e o auditor mais caros da seleção (teto, não média)
    top_c = max(creators, key=lambda x: x.completion_usd_m, default=None)
    top_a = max(auditors, key=lambda x: x.completion_usd_m, default=None)
    round_c = Decimal(0)
    if top_c and top_a:
        per = (top_c.cost_usd(c["gen_in"], c["gen_out"]) * c["gen_calls"]
               + top_a.cost_usd(c["audit_in"], c["audit_out"]) * c["audit_calls"]
               + top_c.cost_usd(c["correction_in"], c["correction_out"]) * c["correction_calls"])
        round_c = per * c["pipelines"]
    return {"research": research, "round_a": round_a, "round_b": round_b, "round_c": round_c}


def plan(rows: list[dict[str, Any]], *, budget_brl: Decimal, fx_rate: Decimal | None, fx_margin: Decimal,
         caps: dict[str, Decimal] | None = None, now: datetime | None = None) -> dict[str, Any]:
    caps = {**DEFAULT_CAPS_USD, **(caps or {})}
    creators = select(rows, caps["creator"], now)
    auditors = select(rows, caps["auditor_scientific"], now)
    # Auditor fixo da Rodada A e pesquisador: o mais barato entre os modelos principais (saída ≥ 25% do teto),
    # para não gastar a triagem no juiz; a escolha é exibida e pode ser trocada.
    main_tier = [x for x in auditors if x.completion_usd_m >= caps["auditor_scientific"] / 4] or auditors
    fixed = min(main_tier, key=lambda x: x.completion_usd_m, default=None)
    cost = estimate(creators, auditors, fixed, fixed)
    total_usd = sum(cost.values(), Decimal(0))
    rounds = {k: {"usd": _s(v), "brl": _s(usd_to_brl(v, fx_rate, fx_margin)) if fx_rate else None}
              for k, v in cost.items()}
    total_brl = usd_to_brl(total_usd, fx_rate, fx_margin) if fx_rate else None
    first = cost["research"] + cost["round_a"] + cost["round_b"]
    first_brl = usd_to_brl(first, fx_rate, fx_margin) if fx_rate else None
    families = {c.family for c in creators}
    return {
        "generated_at": (now or datetime.now(UTC)).isoformat(),
        "catalog_models": len(rows),
        "filters": {"min_context": MIN_CONTEXT, "max_age_days": MAX_AGE_DAYS, "structured_outputs": True,
                    "caps_usd_per_m_output": {k: _s(v) for k, v in caps.items()}, "excluded_words": EXCLUDE_WORDS},
        "creators": [c.as_dict() for c in creators],
        "auditors": [c.as_dict() for c in auditors],
        "fixed_auditor": fixed.model_id if fixed else None,
        "missing_families": [f for f in FAMILIES if f not in families],
        "rounds": rounds,
        "total": {"usd": _s(total_usd), "brl": _s(total_brl) if total_brl is not None else None},
        "research_a_b": {"usd": _s(first), "brl": _s(first_brl) if first_brl is not None else None},
        "budget_brl": _s(budget_brl),
        "fits": None if total_brl is None else total_brl <= budget_brl,
        "fits_a_b": None if first_brl is None else first_brl <= budget_brl,
        "assumptions": ASSUMPTIONS, "reasoning_factor": _s(REASONING_FACTOR),
        "fx": {"rate": _s(fx_rate) if fx_rate else None, "margin": _s(fx_margin)},
        "note": ("Estimativa. O orçamento interrompe as chamadas antes de ultrapassar o limite autorizado; "
                 "nenhuma chamada paga acontece sem a aprovação desta lista."),
    }


def to_markdown(p: dict[str, Any]) -> str:
    def brl(x):
        return f"R$ {x['brl']}" if x.get("brl") else f"US$ {x['usd']} (sem câmbio cadastrado)"

    lines = [f"# Etapa 1: candidatos e custo estimado ({p['generated_at'][:10]})", "",
             f"Catálogo com {p['catalog_models']} modelos. Filtros: saída estruturada, contexto ≥ "
             f"{p['filters']['min_context']:,} tokens, lançado nos últimos {p['filters']['max_age_days']} dias, "
             f"saída até US$ {p['filters']['caps_usd_per_m_output']['creator']}/M tokens.", "",
             "## Criadores (um por família)", "", "| Família | Modelo | Entrada US$/M | Saída US$/M | Raciocínio |",
             "|---|---|---|---|---|"]
    for c in p["creators"]:
        lines.append(f"| {c['family']} | `{c['model_id']}` | {c['prompt_usd_m']} | {c['completion_usd_m']} | "
                     f"{'sim' if c['reasoning'] else 'não'} |")
    if p["missing_families"]:
        lines += ["", f"Sem candidato elegível: {', '.join(p['missing_families'])}."]
    lines += ["", f"Auditor fixo da Rodada A e pesquisa compartilhada: `{p['fixed_auditor']}`.",
              "Rodada B: os 3 auditores mais capazes (por preço) da mesma lista contra o conjunto de defeitos "
              "conhecidos (dev).", "", "## Custo estimado", "", "| Etapa | Estimativa |", "|---|---|"]
    names = {"research": "Pesquisa compartilhada", "round_a": "Rodada A (triagem de criadores)",
             "round_b": "Rodada B (auditores)", "round_c": "Rodada C (combinações)"}
    for k, label in names.items():
        lines.append(f"| {label} | {brl(p['rounds'][k])} |")
    lines += [f"| **Total** | **{brl(p['total'])}** |", "",
              f"Orçamento autorizado: R$ {p['budget_brl']}. Pesquisa + A + B: {brl(p['research_a_b'])}.", "",
              p["note"]]
    return "\n".join(lines) + "\n"


def latest_rows(db, provider: str = "openrouter") -> list[dict[str, Any]]:
    """Última versão de cada modelo do catálogo sincronizado."""
    from sqlalchemy import select

    from cardfactory.db.models import ModelCatalogEntry

    with db.session() as s:
        seen: set[str] = set()
        out = []
        for m in s.execute(select(ModelCatalogEntry).where(ModelCatalogEntry.provider == provider)
                           .order_by(ModelCatalogEntry.fetched_at.desc())).scalars():
            if m.model_id in seen:
                continue
            seen.add(m.model_id)
            out.append({"model_id": m.model_id, "name": m.name, "pricing": dict(m.pricing or {}),
                        "context_length": m.context_length, "supported_parameters": list(m.supported_parameters or []),
                        "raw": {"created": (m.raw or {}).get("created")}})
        return out


def plan_from_db(db, finance, *, budget_brl: Decimal, caps: dict[str, Decimal] | None = None) -> dict[str, Any]:
    with db.session() as s:
        fx = finance.latest_fx(s)
        rate, margin = (Decimal(fx.rate), Decimal(fx.margin)) if fx else (None, Decimal("0.10"))
    return plan(latest_rows(db), budget_brl=budget_brl, fx_rate=rate, fx_margin=margin, caps=caps)
