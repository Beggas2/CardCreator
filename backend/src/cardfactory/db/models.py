"""Modelo relacional da Fase 1 (ver DATA_MODEL.md). Tabelas das fases 2–4 entram por novas migrações."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cardfactory.ids import new_id


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


def _id(prefix: str):
    return mapped_column(String(40), primary_key=True, default=lambda: new_id(prefix))


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# ------------------------------------------------------------------ organização
class Project(Timestamped, Base):
    __tablename__ = "project"
    id: Mapped[str] = _id("prj")
    name: Mapped[str] = mapped_column(String(200), unique=True)
    area: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    deck_prefix: Mapped[str] = mapped_column(String(50), default="IGOR::")
    default_notetype: Mapped[str] = mapped_column(String(100), default="Basic")
    pedagogical_profile_id: Mapped[str | None] = mapped_column(ForeignKey("pedagogical_profile.id"))


class PedagogicalProfile(Timestamped, Base):
    """[append-only por versão]"""

    __tablename__ = "pedagogical_profile"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[str] = _id("pp")
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))


class Production(Timestamped, Base):
    __tablename__ = "production"
    id: Mapped[str] = _id("prd")
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"))
    mode: Mapped[str] = mapped_column(String(40))
    theme: Mapped[str] = mapped_column(String(300))
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    depth: Mapped[str] = mapped_column(String(40), default="standard")
    target_cards: Mapped[int] = mapped_column(Integer, default=20)
    research_mode: Mapped[str] = mapped_column(String(20), default="HYBRID")
    batch_size: Mapped[int] = mapped_column(Integer, default=20)
    concurrency: Mapped[int] = mapped_column(Integer, default=2)
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    state: Mapped[str] = mapped_column(String(30), default="DRAFT")


class StageModelConfig(Base):
    __tablename__ = "stage_model_config"
    __table_args__ = (UniqueConstraint("production_id", "stage"),)
    id: Mapped[str] = _id("smc")
    production_id: Mapped[str] = mapped_column(ForeignKey("production.id"))
    stage: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(200))
    routing: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reasoning: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    fallback_policy: Mapped[str] = mapped_column(String(30), default="NONE")
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=4000)


# ------------------------------------------------------------------ orquestração
class Run(Timestamped, Base):
    __tablename__ = "run"
    id: Mapped[str] = _id("run")
    production_id: Mapped[str] = mapped_column(ForeignKey("production.id"))
    mode: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(20), default="PENDING")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    note: Mapped[str] = mapped_column(Text, default="")


class Batch(Timestamped, Base):
    __tablename__ = "batch"
    id: Mapped[str] = _id("bat")
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"))
    stage: Mapped[str] = mapped_column(String(40))
    objective_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    card_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    size: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="PENDING")


class Task(Timestamped, Base):
    __tablename__ = "task"
    id: Mapped[str] = _id("tsk")
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batch.id"))
    stage: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(60))
    state: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(60))
    lease_expires_at: Mapped[datetime | None]
    not_before: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    required: Mapped[bool] = mapped_column(Boolean, default=True)


class TaskDependency(Base):
    __tablename__ = "task_dependency"
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), primary_key=True)
    depends_on_task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), primary_key=True)


# ------------------------------------------------------------------ provedores e prompts
class ModelCatalogEntry(Base):
    __tablename__ = "model_catalog"
    __table_args__ = (UniqueConstraint("provider", "model_id", "fetched_at"),)
    id: Mapped[str] = _id("mdl")
    provider: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(200), index=True)
    name: Mapped[str] = mapped_column(String(300), default="")
    pricing: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context_length: Mapped[int | None] = mapped_column(Integer)
    max_completion_tokens: Mapped[int | None] = mapped_column(Integer)
    supported_parameters: Mapped[list[Any]] = mapped_column(JSON, default=list)
    input_modalities: Mapped[list[Any]] = mapped_column(JSON, default=list)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)


class Prompt(Timestamped, Base):
    __tablename__ = "prompt"
    id: Mapped[str] = _id("pr")
    key: Mapped[str] = mapped_column(String(60), unique=True)  # ex.: role:creator, policy:scientific
    kind: Mapped[str] = mapped_column(String(10))  # ROLE | POLICY
    description: Mapped[str] = mapped_column(Text, default="")
    active_version_id: Mapped[str | None] = mapped_column(String(40))


class PromptVersion(Timestamped, Base):
    """[append-only] Nunca atualizado após inserção."""

    __tablename__ = "prompt_version"
    __table_args__ = (UniqueConstraint("prompt_id", "version"),)
    id: Mapped[str] = _id("pv")
    prompt_id: Mapped[str] = mapped_column(ForeignKey("prompt.id"))
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    req_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    parent_version_id: Mapped[str | None] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(100), default="system")
    note: Mapped[str] = mapped_column(Text, default="")


class LLMCall(Timestamped, Base):
    __tablename__ = "llm_call"
    id: Mapped[str] = _id("call")
    task_id: Mapped[str | None] = mapped_column(ForeignKey("task.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40), default="")
    provider: Mapped[str] = mapped_column(String(40))
    requested_model: Mapped[str] = mapped_column(String(200))
    served_model: Mapped[str | None] = mapped_column(String(200))
    served_provider: Mapped[str | None] = mapped_column(String(100))
    model_mismatch: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_version_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    prompt_hash: Mapped[str] = mapped_column(String(64), default="")
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    state: Mapped[str] = mapped_column(String(20), default="RESERVED", index=True)
    finish_reason: Mapped[str | None] = mapped_column(String(40))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    tokens_cached: Mapped[int | None] = mapped_column(Integer)
    tokens_reasoning: Mapped[int | None] = mapped_column(Integer)
    estimated_max_usd: Mapped[str] = mapped_column(String(40), default="0")
    cost_usd: Mapped[str | None] = mapped_column(String(40))
    generation_id: Mapped[str | None] = mapped_column(String(100))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_text: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    attempt_of: Mapped[str | None] = mapped_column(String(160))
    finished_at: Mapped[datetime | None]


# ------------------------------------------------------------------ finanças
class Budget(Timestamped, Base):
    __tablename__ = "budget"
    __table_args__ = (UniqueConstraint("scope", "scope_ref"),)
    id: Mapped[str] = _id("bud")
    scope: Mapped[str] = mapped_column(String(20))  # PROJECT | EXPERIMENT | RUN | STAGE | BATCH | MODEL
    scope_ref: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(200), default="")
    limit_brl: Mapped[str] = mapped_column(String(40))
    parent_budget_id: Mapped[str | None] = mapped_column(ForeignKey("budget.id"))


class BudgetLedger(Timestamped, Base):
    """[append-only] Saldo = soma do razão."""

    __tablename__ = "budget_ledger"
    id: Mapped[str] = _id("led")
    budget_id: Mapped[str] = mapped_column(ForeignKey("budget.id"), index=True)
    llm_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_call.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # RESERVE | RELEASE | CONFIRM | ADJUST
    amount_usd: Mapped[str] = mapped_column(String(40))
    amount_brl: Mapped[str] = mapped_column(String(40))
    fx_rate_id: Mapped[str | None] = mapped_column(ForeignKey("fx_rate.id"))
    author: Mapped[str] = mapped_column(String(100), default="system")
    note: Mapped[str] = mapped_column(Text, default="")


class FxRate(Timestamped, Base):
    __tablename__ = "fx_rate"
    id: Mapped[str] = _id("fx")
    currency_pair: Mapped[str] = mapped_column(String(10), default="USDBRL")
    rate: Mapped[str] = mapped_column(String(40))
    margin: Mapped[str] = mapped_column(String(40), default="0.10")
    source: Mapped[str] = mapped_column(String(200), default="manual")
    valid_on: Mapped[str] = mapped_column(String(10))


class SpendAuthorization(Timestamped, Base):
    __tablename__ = "spend_authorization"
    id: Mapped[str] = _id("auth")
    scope_budget_id: Mapped[str] = mapped_column(ForeignKey("budget.id"))
    amount_brl: Mapped[str] = mapped_column(String(40))
    granted_by: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime | None]
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")


# ------------------------------------------------------------------ cards (núcleo; enriquecido na Fase 3)
class Card(Timestamped, Base):
    __tablename__ = "card"
    __table_args__ = (UniqueConstraint("project_id", "anki_guid"),)
    id: Mapped[str] = _id("crd")
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    card_key: Mapped[str] = mapped_column(String(40), unique=True, default=lambda: new_id())
    anki_guid: Mapped[str | None] = mapped_column(String(100))
    notetype: Mapped[str] = mapped_column(String(100), default="Basic")
    state: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    quarantine: Mapped[bool] = mapped_column(Boolean, default=False)
    origin: Mapped[str] = mapped_column(String(20), default="GENERATED")
    production_id: Mapped[str | None] = mapped_column(ForeignKey("production.id"))


class CardVersion(Timestamped, Base):
    """[append-only]"""

    __tablename__ = "card_version"
    __table_args__ = (UniqueConstraint("card_id", "version_no"),)
    id: Mapped[str] = _id("cv")
    card_id: Mapped[str] = mapped_column(ForeignKey("card.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(10), default="2.1")
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    deck_path: Mapped[str] = mapped_column(String(500), default="")
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    author_type: Mapped[str] = mapped_column(String(10), default="AI")
    created_by_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_call.id"))
    objective_change: Mapped[str] = mapped_column(String(20), default="EQUIVALENT")
    content_hash: Mapped[str] = mapped_column(String(64))


class CardStateEvent(Timestamped, Base):
    """[append-only] Histórico de transições de estado do card."""

    __tablename__ = "card_state_event"
    id: Mapped[str] = _id("cse")
    card_id: Mapped[str] = mapped_column(ForeignKey("card.id"), index=True)
    from_state: Mapped[str] = mapped_column(String(30))
    to_state: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(100))
    actor_type: Mapped[str] = mapped_column(String(10))  # AI | HUMAN | SYSTEM
    reason: Mapped[str] = mapped_column(Text, default="")
