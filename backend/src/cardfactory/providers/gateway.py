"""Único caminho para chamar modelos: orçamento → registro → provedor → validação → custo.

Garante FIN-002/003/005/012, PRV-004/005/006/007/008/013 e PRM-005.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import jsonschema
from sqlalchemy import select

from cardfactory.db import Database
from cardfactory.db.models import LLMCall, ModelCatalogEntry
from cardfactory.finance.budget import FinanceService
from cardfactory.finance.estimator import estimate_call
from cardfactory.finance.money import q
from cardfactory.providers.base import LLMProvider, LLMRequest, LLMResult


class GatewayError(Exception):
    pass


class UncertainCallError(GatewayError):
    """Resultado incerto: pode ter sido cobrado. Nunca repetir automaticamente (PRV-007)."""


class CallFailedError(GatewayError):
    def __init__(self, message: str, *, retryable: bool = False, retry_after_s: float | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_s = retry_after_s


class ModelMismatchError(GatewayError):
    pass


@dataclass
class GatewayResult:
    call_id: str
    status: str  # ok | truncated
    parsed: Any
    text: str | None
    result: LLMResult


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0, retry_after: float | None = None) -> float:
    """Backoff exponencial com jitter completo; respeita Retry-After quando informado."""
    if retry_after is not None:
        return min(cap, retry_after) + random.uniform(0, 0.5)  # noqa: S311
    return random.uniform(0, min(cap, base * (2 ** attempt)))  # noqa: S311


class LLMGateway:
    def __init__(self, db: Database, finance: FinanceService, provider: LLMProvider, *,
                 max_unbilled_retries: int = 3, sleep=asyncio.sleep, backoff_base: float = 1.0):
        self.db = db
        self.finance = finance
        self.provider = provider
        self.max_unbilled_retries = max_unbilled_retries
        self._sleep = sleep
        self._backoff_base = backoff_base

    # ------------------------------------------------------------ catálogo
    async def sync_catalog(self) -> int:
        models = await self.provider.catalog()
        now = datetime.now(UTC)
        with self.db.write() as s:
            for m in models:
                s.add(ModelCatalogEntry(provider=self.provider.name, model_id=m.model_id, name=m.name,
                                        pricing=m.pricing, context_length=m.context_length,
                                        max_completion_tokens=m.max_completion_tokens,
                                        supported_parameters=m.supported_parameters,
                                        input_modalities=m.input_modalities, raw=m.raw, fetched_at=now))
        return len(models)

    def pricing_for(self, model_id: str) -> dict | None:
        with self.db.session() as s:
            row = s.execute(select(ModelCatalogEntry).where(ModelCatalogEntry.provider == self.provider.name,
                                                            ModelCatalogEntry.model_id == model_id)
                            .order_by(ModelCatalogEntry.fetched_at.desc()).limit(1)).scalar_one_or_none()
            return dict(row.pricing) if row else None

    # ------------------------------------------------------------ chamada
    async def call(self, req: LLMRequest, *, budget_ids: list[str], task_id: str | None = None, stage: str = "",
                   prompt_version_ids: list[str] | None = None, prompt_hash: str = "",
                   web_searches: int = 0, web_search_price_usd: Decimal | None = None,
                   critical: bool = False, repair_attempts: int = 1) -> GatewayResult:
        """Executa uma chamada lógica identificada por `req.idempotency_key`.

        Cada tentativa física recebe a chave `<chave>` ou `<chave>#r<n>` e um registro próprio.
        Repetir a mesma chave lógica nunca reenvia algo que possa ter sido cobrado (PRV-007).
        """
        attempts = self._attempts(req.idempotency_key)
        seq = 0
        if attempts:
            replay = self._replay(attempts, req)
            if replay is not None:
                return replay
            seq = len(attempts)  # todas as anteriores falharam sem cobrança: pode tentar de novo

        messages = list(req.messages)
        unbilled_retries = 0
        last_error = ""
        while True:
            key = req.idempotency_key if seq == 0 else f"{req.idempotency_key}#r{seq}"
            seq += 1
            attempt_req = LLMRequest(**{**req.__dict__, "idempotency_key": key, "messages": messages})
            call_id = self._reserve(attempt_req, budget_ids, task_id, stage, prompt_version_ids or [], prompt_hash,
                                    web_searches, web_search_price_usd, repair_attempts, parent=req.idempotency_key)
            res = await self.provider.complete(attempt_req)
            outcome = self._settle(call_id, attempt_req, res, critical)
            if outcome == "retry_unbilled":
                last_error = res.error.message if res.error else "erro"
                ra = res.error.retry_after_s if res.error else None
                if unbilled_retries < self.max_unbilled_retries:
                    await self._sleep(backoff_delay(unbilled_retries, self._backoff_base, retry_after=ra))
                    unbilled_retries += 1
                    continue
                raise CallFailedError(f"falha após {unbilled_retries + 1} tentativas sem cobrança: {last_error}",
                                      retryable=True, retry_after_s=ra)
            if outcome == "fail_unbilled":
                raise CallFailedError(res.error.message if res.error else "falha", retryable=False)
            if outcome == "uncertain":
                raise UncertainCallError(f"chamada {call_id} em estado incerto; requer reconciliação")
            if outcome == "mismatch":
                raise ModelMismatchError(f"modelo servido {res.served_model} ≠ solicitado {req.model_id}")
            if outcome == "truncated":
                return GatewayResult(call_id, "truncated", None, res.output_text, res)
            # outcome == ok: valida saída
            parsed, err = self._validate(res.output_text, req.response_schema)
            if err is None:
                return GatewayResult(call_id, "ok", parsed, res.output_text, res)
            self._mark(call_id, state="INVALID_OUTPUT", error={"validation": err[:2000]})
            if repair_attempts <= 0:
                raise CallFailedError(f"saída inválida: {err[:300]}", retryable=False)
            # Uma tentativa de reparo com o erro de validação (custo já previsto na estimativa).
            repair_attempts -= 1
            messages = messages + [
                {"role": "assistant", "content": res.output_text or ""},
                {"role": "user", "content": "A resposta anterior não é válida segundo o schema: "
                                            f"{err[:1500]}. Responda novamente apenas com JSON válido."},
            ]

    # ------------------------------------------------------------ internos
    def _attempts(self, key: str) -> list[LLMCall]:
        """Todas as tentativas físicas de uma chamada lógica, na ordem em que foram feitas."""
        with self.db.session() as s:
            rows = list(s.execute(select(LLMCall).where(
                (LLMCall.idempotency_key == key) | (LLMCall.attempt_of == key))).scalars())

        def seq(c: LLMCall) -> int:
            k = c.idempotency_key
            return 0 if k == key else int(k.rsplit("#r", 1)[1]) if "#r" in k else 0

        return sorted(rows, key=seq)

    def _replay(self, attempts: list[LLMCall], req: LLMRequest) -> GatewayResult | None:
        """Decide o que fazer com uma chave já usada. None = pode tentar de novo (nada foi cobrado)."""
        for c in attempts:
            if c.state in ("RESERVED", "SENT", "UNCERTAIN", "FAILED_BILLED", "RECONCILED"):
                raise UncertainCallError(f"chamada {c.id} com mesma chave está em {c.state}; não repetir")
        last = attempts[-1]
        if last.state == "SUCCEEDED" and last.output_text is not None:
            parsed, err = self._validate(last.output_text, req.response_schema)
            if err is None:
                return GatewayResult(last.id, "ok", parsed, last.output_text,
                                     LLMResult("ok", last.output_text, last.served_model, last.served_provider,
                                               last.generation_id, last.finish_reason))
        if last.state == "TRUNCATED":
            return GatewayResult(last.id, "truncated", None, last.output_text,
                                 LLMResult("truncated", last.output_text, last.served_model, last.served_provider,
                                           last.generation_id, last.finish_reason))
        if all(c.state == "FAILED_UNBILLED" for c in attempts):
            return None
        raise CallFailedError(f"chamada {last.id} com mesma chave terminou em {last.state}", retryable=False)

    def _reserve(self, req: LLMRequest, budget_ids, task_id, stage, pv_ids, prompt_hash, web_searches,
                 web_search_price, repair_attempts, parent) -> str:
        pricing = None if not self.provider.paid else self.pricing_for(req.model_id)
        chars = len(json.dumps(req.messages, ensure_ascii=False))
        est = estimate_call(pricing, input_chars=chars, max_output_tokens=req.max_output_tokens,
                            web_searches=web_searches, web_search_price_usd=web_search_price,
                            repair_attempts=repair_attempts, free_provider=not self.provider.paid)
        with self.db.write() as s:
            call = LLMCall(task_id=task_id, stage=stage, provider=self.provider.name, requested_model=req.model_id,
                           prompt_version_ids=pv_ids, prompt_hash=prompt_hash,
                           request_hash=_sha({"m": req.messages, "s": req.response_schema, "model": req.model_id}),
                           idempotency_key=req.idempotency_key, attempt_of=parent)
            self.finance.reserve(s, call, budget_ids, est, paid_provider=self.provider.paid)
            call_id = call.id
        # Marca SENT antes de enviar: se o processo cair agora, a chamada fica incerta (não repetida).
        self._mark(call_id, state="SENT")
        return call_id

    def _mark(self, call_id: str, **fields) -> None:
        with self.db.write() as s:
            c = s.get(LLMCall, call_id)
            for k, v in fields.items():
                setattr(c, k, v)

    def _settle(self, call_id: str, req: LLMRequest, res: LLMResult, critical: bool) -> str:
        with self.db.write() as s:
            c = s.get(LLMCall, call_id)
            c.finished_at = datetime.now(UTC)
            c.latency_ms = res.latency_ms
            c.generation_id = res.generation_id
            c.served_model = res.served_model
            c.served_provider = res.served_provider
            c.finish_reason = res.finish_reason
            u = res.usage
            c.tokens_in, c.tokens_out = u.tokens_in, u.tokens_out
            c.tokens_cached, c.tokens_reasoning = u.tokens_cached, u.tokens_reasoning
            c.output_text = res.output_text
            c.citations = res.citations or None
            if res.error:
                c.error = {"cls": res.error.cls, "message": res.error.message, "status": res.error.status,
                           "error_type": res.error.error_type}

            if res.status == "error" and res.error and res.error.cls in ("rate_limited", "transient",
                                                                          "pre_generation"):
                c.state = "FAILED_UNBILLED"
                self.finance.release_unbilled(s, c, res.error.message)
                return "retry_unbilled" if res.error.cls in ("rate_limited", "transient") else "fail_unbilled"
            if res.status in ("uncertain", "error"):
                c.state = "UNCERTAIN"
                if u.cost_usd is not None:
                    self.finance.confirm(s, c, u.cost_usd)
                return "uncertain"

            # Houve geração: custo real confirmado (ou pendente de reconciliação).
            if u.cost_usd is not None:
                self.finance.confirm(s, c, u.cost_usd)
            mismatch = bool(res.served_model) and not _same_model(req.model_id, res.served_model)
            c.model_mismatch = mismatch
            if mismatch and (critical or not req.routing.allow_fallbacks):
                c.state = "FAILED_BILLED"
                return "mismatch"
            c.state = "SUCCEEDED" if res.status == "ok" else "TRUNCATED"
            return "ok" if res.status == "ok" else "truncated"

    @staticmethod
    def _validate(text: str | None, schema: dict | None) -> tuple[Any, str | None]:
        if schema is None:
            return text, None
        if not text:
            return None, "resposta vazia"
        stripped = text.strip()
        if stripped.startswith("```"):  # modo sem gramática: alguns modelos cercam o JSON com ```json
            stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
            stripped = stripped.rsplit("```", 1)[0]
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as e:
            return None, f"JSON inválido: {e}"
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            return None, f"{e.message} em {list(e.absolute_path)}"
        return data, None

    # ------------------------------------------------------------ reconciliação
    async def reconcile(self) -> dict[str, int]:
        """Busca custo real de chamadas pendentes com generation_id (FIN-005)."""
        done = skipped = 0
        for item in self.finance.pending_reconciliation():
            if not item["generation_id"]:
                skipped += 1
                continue
            rec = await self.provider.lookup_cost(item["generation_id"])
            if rec is None or rec.total_cost_usd is None:
                skipped += 1
                continue
            with self.db.write() as s:
                c = s.get(LLMCall, item["id"])
                self.finance.confirm(s, c, rec.total_cost_usd)
                if c.state in ("UNCERTAIN", "SENT"):
                    c.state = "RECONCILED"
            done += 1
        return {"reconciled": done, "pending": skipped}


def _same_model(requested: str, served: str) -> bool:
    """O OpenRouter pode devolver slug canônico com sufixo de data; compara prefixo do slug."""
    r, s = requested.split(":")[0], served.split(":")[0]
    return s == r or s.startswith(r + "-") or r.startswith(s + "-")


__all__ = ["LLMGateway", "GatewayResult", "UncertainCallError", "CallFailedError", "ModelMismatchError", "q"]
