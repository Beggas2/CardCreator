"""Modelo relacional (ver DATA_MODEL.md). Cada fase acrescenta tabelas por nova migração."""

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
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batch.id"))


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
    cognitive_type: Mapped[str | None] = mapped_column(String(1))
    layout: Mapped[str | None] = mapped_column(String(20))
    didactic_order: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    restored_from_version: Mapped[int | None] = mapped_column(Integer)


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


# ------------------------------------------------------------------ biblioteca científica (Fase 2)
class Source(Timestamped, Base):
    """Identidade lógica de um documento (ex.: "PCDT de hipertensão"). Título só é confirmado após leitura."""

    __tablename__ = "source"
    id: Mapped[str] = _id("src")
    title_claimed: Mapped[str] = mapped_column(String(500), default="")
    title_confirmed: Mapped[str | None] = mapped_column(String(500))
    institution: Mapped[str] = mapped_column(String(300), default="")
    source_tier: Mapped[str] = mapped_column(String(30), default="UNCLASSIFIED")
    doc_type: Mapped[str] = mapped_column(String(60), default="")
    doi: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(2000))
    license: Mapped[str] = mapped_column(String(200), default="")
    rights_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    created_by: Mapped[str] = mapped_column(String(100), default="system")
    notes: Mapped[str] = mapped_column(Text, default="")


class SourceVersion(Timestamped, Base):
    __tablename__ = "source_version"
    id: Mapped[str] = _id("srv")
    source_id: Mapped[str] = mapped_column(ForeignKey("source.id"), index=True)
    version_label: Mapped[str] = mapped_column(String(100), default="")
    published_at: Mapped[str | None] = mapped_column(String(10))
    page_updated_at: Mapped[str | None] = mapped_column(String(10))
    effective_from: Mapped[str | None] = mapped_column(String(10))
    effective_to: Mapped[str | None] = mapped_column(String(10))
    validity_status: Mapped[str] = mapped_column(String(20), default="UNCERTAIN")
    supersedes_version_id: Mapped[str | None] = mapped_column(ForeignKey("source_version.id"))
    population: Mapped[str] = mapped_column(String(300), default="")
    context: Mapped[str] = mapped_column(String(300), default="")


class Document(Timestamped, Base):
    __tablename__ = "document"
    id: Mapped[str] = _id("doc")
    source_version_id: Mapped[str] = mapped_column(ForeignKey("source_version.id"), index=True)
    access_state: Mapped[str] = mapped_column(String(25), default="FOUND", index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    blob_path: Mapped[str | None] = mapped_column(String(500))
    mime: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    pages: Mapped[int | None] = mapped_column(Integer)
    accessed_at: Mapped[datetime | None]
    fetch_url: Mapped[str | None] = mapped_column(String(2000))
    origin: Mapped[str] = mapped_column(String(20), default="FETCH")  # FETCH | USER_UPLOAD | SEARCH
    parse_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pending_reason: Mapped[str | None] = mapped_column(Text)


class DocumentEvent(Timestamped, Base):
    """[append-only] Transições de estado documental (BIB-003)."""

    __tablename__ = "document_event"
    id: Mapped[str] = _id("dev")
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    from_state: Mapped[str] = mapped_column(String(25))
    to_state: Mapped[str] = mapped_column(String(25))
    actor: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text, default="")


class DocumentSection(Base):
    __tablename__ = "document_section"
    __table_args__ = (UniqueConstraint("document_id", "ordinal"),)
    id: Mapped[str] = _id("sec")
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(500), default="")
    kind: Mapped[str] = mapped_column(String(15), default="TEXT")  # TEXT | TABLE | ALGORITHM | FOOTNOTE
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    parse_quality: Mapped[str] = mapped_column(String(10), default="OK")  # OK | UNCERTAIN | FAILED


class EvidenceSpan(Timestamped, Base):
    __tablename__ = "evidence_span"
    id: Mapped[str] = _id("ev")
    section_id: Mapped[str] = mapped_column(ForeignKey("document_section.id"), index=True)
    quote: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    retrieved_via: Mapped[str] = mapped_column(String(20), default="DOCUMENT")
    created_by_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_call.id"))


class ResearchQuery(Timestamped, Base):
    __tablename__ = "research_query"
    id: Mapped[str] = _id("rq")
    production_id: Mapped[str | None] = mapped_column(ForeignKey("production.id"))
    query: Mapped[str] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(60))
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cost_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_call.id"))
    cache_key: Mapped[str] = mapped_column(String(64), index=True)


# ------------------------------------------------------------------ conhecimento (Fase 2)
class ClinicalEntity(Timestamped, Base):
    __tablename__ = "clinical_entity"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[str] = _id("ent")
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    synonyms: Mapped[list[Any]] = mapped_column(JSON, default=list)
    home_deck_path: Mapped[str] = mapped_column(String(500), default="")


class MapDimension(Timestamped, Base):
    __tablename__ = "map_dimension"
    __table_args__ = (UniqueConstraint("entity_id", "dimension_code", "map_origin"),)
    id: Mapped[str] = _id("md")
    entity_id: Mapped[str] = mapped_column(ForeignKey("clinical_entity.id"), index=True)
    dimension_code: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(25))
    justification: Mapped[str] = mapped_column(Text, default="")
    map_origin: Mapped[str] = mapped_column(String(15), default="CREATOR")  # CREATOR | INDEPENDENT
    origin_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_call.id"))


class DecisionPoint(Timestamped, Base):
    __tablename__ = "decision_point"
    id: Mapped[str] = _id("dp")
    entity_id: Mapped[str] = mapped_column(ForeignKey("clinical_entity.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    condition_axis: Mapped[str] = mapped_column(String(60), default="")
    disposition_relevant: Mapped[bool] = mapped_column(Boolean, default=False)


class LearningObjective(Timestamped, Base):
    __tablename__ = "learning_objective"
    id: Mapped[str] = _id("obj")
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    production_id: Mapped[str | None] = mapped_column(ForeignKey("production.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("clinical_entity.id"), index=True)
    area: Mapped[str] = mapped_column(String(200), default="")
    subtopic: Mapped[str] = mapped_column(String(300), default="")
    knowledge_type: Mapped[str] = mapped_column(String(60), default="")
    knowledge_level: Mapped[str] = mapped_column(String(15), default="FACTUAL")
    description: Mapped[str] = mapped_column(Text)
    clinical_relevance: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    exam_relevance: Mapped[str] = mapped_column(String(10), default="UNKNOWN")
    purpose: Mapped[str] = mapped_column(String(30), default="")
    necessity: Mapped[str] = mapped_column(String(15), default="REQUIRED")
    coverage_state: Mapped[str] = mapped_column(String(25), default="ABSENT", index=True)
    planned_cards: Mapped[int] = mapped_column(Integer, default=1)
    planned_rationale: Mapped[str] = mapped_column(Text, default="")
    lease_owner: Mapped[str | None] = mapped_column(String(60))
    lease_expires_at: Mapped[datetime | None]
    origin_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_call.id"))


class ObjectiveDependency(Base):
    __tablename__ = "objective_dependency"
    objective_id: Mapped[str] = mapped_column(ForeignKey("learning_objective.id"), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("learning_objective.id"), primary_key=True)


class Claim(Timestamped, Base):
    __tablename__ = "claim"
    id: Mapped[str] = _id("clm")
    objective_id: Mapped[str | None] = mapped_column(ForeignKey("learning_objective.id"), index=True)
    card_version_id: Mapped[str | None] = mapped_column(ForeignKey("card_version.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("clinical_entity.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    component: Mapped[str] = mapped_column(String(20), default="OTHER")
    population: Mapped[str] = mapped_column(String(300), default="")
    scenario: Mapped[str] = mapped_column(String(300), default="")
    criticality: Mapped[str] = mapped_column(String(10), default="NORMAL")
    negation_kind: Mapped[str | None] = mapped_column(String(25))
    numeric: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    origin_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_call.id"))


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), primary_key=True)
    evidence_span_id: Mapped[str] = mapped_column(ForeignKey("evidence_span.id"), primary_key=True)
    supports: Mapped[str] = mapped_column(String(15), default="SUPPORTS")


class ClaimVerdict(Timestamped, Base):
    """[append-only]"""

    __tablename__ = "claim_verdict"
    id: Mapped[str] = _id("cvd")
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), index=True)
    audit_ref: Mapped[str] = mapped_column(String(60), default="")
    verdict: Mapped[str] = mapped_column(String(25))
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    origin_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_call.id"))


class Divergence(Timestamped, Base):
    __tablename__ = "divergence"
    id: Mapped[str] = _id("dvg")
    claim_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    cause: Mapped[str] = mapped_column(String(25), default="TRUE_DISAGREEMENT")
    resolution: Mapped[str] = mapped_column(String(25), default="OPEN")
    notes: Mapped[str] = mapped_column(Text, default="")


class Question(Timestamped, Base):
    __tablename__ = "question"
    __table_args__ = (UniqueConstraint("project_id", "content_hash"),)
    id: Mapped[str] = _id("q")
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batch.id"))
    exam_board: Mapped[str] = mapped_column(String(200), default="")
    year: Mapped[int | None] = mapped_column(Integer)
    institution: Mapped[str] = mapped_column(String(200), default="")
    exam: Mapped[str] = mapped_column(String(200), default="")
    number: Mapped[str] = mapped_column(String(40), default="")
    stem: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    key_preliminary: Mapped[str | None] = mapped_column(String(10))
    key_final: Mapped[str | None] = mapped_column(String(10))
    annulled: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(500), default="")
    split: Mapped[str] = mapped_column(String(12), default="PLANNING")  # PLANNING | EVALUATION
    content_hash: Mapped[str] = mapped_column(String(64))


class QuestionRequirement(Base):
    __tablename__ = "question_requirement"
    id: Mapped[str] = _id("qr")
    question_id: Mapped[str] = mapped_column(ForeignKey("question.id"), index=True)
    objective_id: Mapped[str] = mapped_column(ForeignKey("learning_objective.id"), index=True)
    step: Mapped[str] = mapped_column(String(12))
    coverage_state: Mapped[str] = mapped_column(String(25), default="ABSENT")


# ------------------------------------------------------------------ importações
class ImportBatch(Timestamped, Base):
    __tablename__ = "import_batch"
    id: Mapped[str] = _id("imp")
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # ANKI_EXPORT | QUESTIONS
    filename: Mapped[str] = mapped_column(String(500), default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    format_detected: Mapped[str] = mapped_column(String(40), default="")
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(100), default="")


# ------------------------------------------------------------------ cards, renderização e exportação (Fase 3)
class CardObjective(Base):
    __tablename__ = "card_objective"
    card_version_id: Mapped[str] = mapped_column(ForeignKey("card_version.id"), primary_key=True)
    objective_id: Mapped[str] = mapped_column(ForeignKey("learning_objective.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10), default="PRIMARY")


class RenderedArtifact(Timestamped, Base):
    """HTML derivado e reproduzível de uma versão (TEC-015)."""

    __tablename__ = "rendered_artifact"
    __table_args__ = (UniqueConstraint("card_version_id", "renderer_version", "palette"),)
    id: Mapped[str] = _id("rnd")
    card_version_id: Mapped[str] = mapped_column(ForeignKey("card_version.id"), index=True)
    renderer_version: Mapped[str] = mapped_column(String(20))
    palette: Mapped[str] = mapped_column(String(10), default="dark")
    front_html: Mapped[str] = mapped_column(Text)
    back_html: Mapped[str] = mapped_column(Text)
    html_hash: Mapped[str] = mapped_column(String(64))


class Operation(Timestamped, Base):
    """[append-only] Operações sobre cards (R§37); manifestos derivam daqui."""

    __tablename__ = "operation"
    id: Mapped[str] = _id("op")
    card_id: Mapped[str] = mapped_column(ForeignKey("card.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    from_version_id: Mapped[str | None] = mapped_column(ForeignKey("card_version.id"))
    to_version_id: Mapped[str | None] = mapped_column(ForeignKey("card_version.id"))
    related_card_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    justification: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="APPLIED")
    actor: Mapped[str] = mapped_column(String(100), default="system")
    actor_type: Mapped[str] = mapped_column(String(10), default="SYSTEM")


class MediaAsset(Timestamped, Base):
    __tablename__ = "media_asset"
    id: Mapped[str] = _id("med")
    card_id: Mapped[str] = mapped_column(ForeignKey("card.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="IMAGE")
    finding: Mapped[str] = mapped_column(Text, default="")
    desired_source: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="PENDING")  # PENDING | OBTAINED | REJECTED
    file_name: Mapped[str | None] = mapped_column(String(300))
    sha256: Mapped[str | None] = mapped_column(String(64))
    license: Mapped[str] = mapped_column(String(200), default="")
    rights_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class ValidationFinding(Timestamped, Base):
    __tablename__ = "validation_finding"
    id: Mapped[str] = _id("vf")
    card_version_id: Mapped[str | None] = mapped_column(ForeignKey("card_version.id"), index=True)
    export_run_id: Mapped[str | None] = mapped_column(ForeignKey("export_run.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(10))  # ERROR | WARNING
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="OPEN")  # OPEN | FIXED | JUSTIFIED
    justification: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[str] = mapped_column(String(100), default="")


class ExportRun(Timestamped, Base):
    __tablename__ = "export_run"
    id: Mapped[str] = _id("exp")
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    production_id: Mapped[str | None] = mapped_column(ForeignKey("production.id"))
    mode: Mapped[str] = mapped_column(String(30), default="DECK")
    format: Mapped[str] = mapped_column(String(20))
    version_label: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(12), default="BLOCKED")  # READY | BLOCKED
    files: Mapped[list[Any]] = mapped_column(JSON, default=list)
    card_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # card_key → version_no
    round_trip_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    import_tested: Mapped[str] = mapped_column(String(12), default="NOT_TESTED")  # NOT_TESTED | PASSED | FAILED
    previous_export_id: Mapped[str | None] = mapped_column(ForeignKey("export_run.id"))
    diff: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(100), default="")


# ------------------------------------------------------------------ auditoria (Fase 4)
class Audit(Timestamped, Base):
    """[append-only] Uma passagem de auditoria sobre um card (ou sobre a produção, quando card_version_id é nulo)."""

    __tablename__ = "audit"
    id: Mapped[str] = _id("aud")
    production_id: Mapped[str | None] = mapped_column(ForeignKey("production.id"), index=True)
    card_version_id: Mapped[str | None] = mapped_column(ForeignKey("card_version.id"), index=True)
    kind: Mapped[str] = mapped_column(String(25))  # SCIENTIFIC | PEDAGOGICAL | COVERAGE | SECURITY | TECHNICAL | ...
    llm_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_call.id"))
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context_manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # AUD-001: o que o auditor recebeu


class Defect(Timestamped, Base):
    __tablename__ = "defect"
    id: Mapped[str] = _id("def")
    card_id: Mapped[str | None] = mapped_column(ForeignKey("card.id"), index=True)
    production_id: Mapped[str | None] = mapped_column(ForeignKey("production.id"), index=True)
    audit_id: Mapped[str | None] = mapped_column(ForeignKey("audit.id"))
    category: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(12))
    description: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(12), default="OPEN")  # OPEN | FIXED | JUSTIFIED | ESCALATED
    correction_attempts: Mapped[int] = mapped_column(Integer, default=0)
    origin: Mapped[str] = mapped_column(String(20), default="AI")  # AI | DETERMINISTIC | HUMAN
    resolution_note: Mapped[str] = mapped_column(Text, default="")


class SimilarityPair(Timestamped, Base):
    """Candidatos de duplicação/contradição (DED-002). Nunca geram exclusão automática (DED-003)."""

    __tablename__ = "similarity_pair"
    __table_args__ = (UniqueConstraint("card_a_id", "card_b_id"),)
    id: Mapped[str] = _id("sim")
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    card_a_id: Mapped[str] = mapped_column(ForeignKey("card.id"))
    card_b_id: Mapped[str] = mapped_column(ForeignKey("card.id"))
    layer: Mapped[str] = mapped_column(String(20))  # HASH | NORMALIZED | LEXICAL | NUMERIC | OBJECTIVE
    score: Mapped[str] = mapped_column(String(10), default="")
    kind: Mapped[str | None] = mapped_column(String(30))  # SimilarityKind decidido por IA ou humano
    proposal: Mapped[str] = mapped_column(String(20), default="REVIEW_REQUIRED")
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="OPEN")  # OPEN | CLASSIFIED | RESOLVED


class ProductionVerdict(Timestamped, Base):
    """[append-only] Veredito por dimensão, separado para original e corrigido; nunca média (AUD-014)."""

    __tablename__ = "production_verdict"
    id: Mapped[str] = _id("pv")
    production_id: Mapped[str] = mapped_column(ForeignKey("production.id"), index=True)
    target: Mapped[str] = mapped_column(String(10))  # ORIGINAL | CORRECTED
    dimension: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
