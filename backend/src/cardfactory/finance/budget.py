"""Orçamentos hierárquicos, autorização de gasto, reserva atômica e reconciliação (FIN-001…012)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardfactory.db import Database
from cardfactory.db.models import Budget, BudgetLedger, FxRate, LLMCall, SpendAuthorization
from cardfactory.finance.estimator import CostEstimate
from cardfactory.finance.money import ZERO, D, q, usd_to_brl

INITIAL_EXPERIMENT_SPLIT_BRL = {
    "research_planning": "10",
    "benchmark": "15",
    "generation": "20",
    "audit_scientific": "25",
    "audit_pedagogical": "10",
    "classification_dedup": "5",
    "reserve_corrections": "15",
}


class BudgetError(Exception):
    pass


class BudgetExceededError(BudgetError):
    pass


class UnsafeEstimateError(BudgetError):
    pass


class SpendNotAuthorizedError(BudgetError):
    pass


@dataclass
class BudgetStatus:
    budget_id: str
    label: str
    limit_brl: Decimal
    confirmed_brl: Decimal
    reserved_brl: Decimal

    @property
    def available_brl(self) -> Decimal:
        return self.limit_brl - self.confirmed_brl - self.reserved_brl

    def as_dict(self) -> dict:
        return {
            "budget_id": self.budget_id,
            "label": self.label,
            "limit_brl": q(self.limit_brl),
            "confirmed_brl": q(self.confirmed_brl),
            "reserved_brl": q(self.reserved_brl),
            "available_brl": q(self.available_brl),
        }


def _sum(s: Session, budget_id: str, kind: str) -> Decimal:
    rows = s.execute(
        select(BudgetLedger.amount_brl).where(BudgetLedger.budget_id == budget_id, BudgetLedger.kind == kind)
    ).scalars()
    return sum((D(v) for v in rows), ZERO)


def budget_status(s: Session, budget: Budget) -> BudgetStatus:
    reserved = _sum(s, budget.id, "RESERVE") - _sum(s, budget.id, "RELEASE")
    confirmed = _sum(s, budget.id, "CONFIRM") + _sum(s, budget.id, "ADJUST")
    return BudgetStatus(budget.id, budget.label, D(budget.limit_brl), confirmed, reserved)


class FinanceService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ configuração
    def create_budget(self, scope: str, scope_ref: str, limit_brl: str, label: str = "",
                      parent_id: str | None = None) -> str:
        with self.db.write() as s:
            b = Budget(scope=scope, scope_ref=scope_ref, limit_brl=q(D(limit_brl)), label=label or scope_ref,
                       parent_budget_id=parent_id)
            s.add(b)
            s.flush()
            return b.id

    def seed_experiment(self, project_budget_id: str, experiment_ref: str = "experimento-100") -> dict[str, str]:
        """Cria o orçamento de R$100 e a divisão inicial por etapa (configurável, E§28)."""
        exp = self.create_budget("EXPERIMENT", experiment_ref, "100", "Experimento inicial R$100", project_budget_id)
        ids = {"experiment": exp}
        for stage, amount in INITIAL_EXPERIMENT_SPLIT_BRL.items():
            ids[stage] = self.create_budget("STAGE", f"{experiment_ref}:{stage}", amount, stage, exp)
        return ids

    def set_fx_rate(self, rate: str, margin: str = "0.10", source: str = "manual", valid_on: str | None = None) -> str:
        with self.db.write() as s:
            fx = FxRate(rate=q(D(rate)), margin=str(D(margin)), source=source,
                        valid_on=valid_on or datetime.now(UTC).date().isoformat())
            s.add(fx)
            s.flush()
            return fx.id

    def authorize_spend(self, budget_id: str, amount_brl: str, granted_by: str, note: str = "",
                        expires_at: datetime | None = None) -> str:
        if not granted_by.strip():
            raise SpendNotAuthorizedError("autorização exige identificação de quem autoriza")
        with self.db.write() as s:
            a = SpendAuthorization(scope_budget_id=budget_id, amount_brl=q(D(amount_brl)), granted_by=granted_by,
                                   note=note, expires_at=expires_at)
            s.add(a)
            s.flush()
            return a.id

    def revoke_authorization(self, auth_id: str) -> None:
        with self.db.write() as s:
            a = s.get(SpendAuthorization, auth_id)
            if a:
                a.revoked = True

    # ------------------------------------------------------------ consultas
    def status(self, budget_id: str) -> BudgetStatus:
        with self.db.session() as s:
            return budget_status(s, s.get(Budget, budget_id))

    def all_status(self) -> list[dict]:
        with self.db.session() as s:
            return [budget_status(s, b).as_dict() | {"scope": b.scope, "scope_ref": b.scope_ref,
                                                     "parent_budget_id": b.parent_budget_id}
                    for b in s.execute(select(Budget).order_by(Budget.created_at)).scalars()]

    def chain(self, s: Session, budget_ids: list[str]) -> list[Budget]:
        """Orçamentos informados + todos os ancestrais (uma chamada é cobrada em toda a cadeia)."""
        seen: dict[str, Budget] = {}
        for bid in budget_ids:
            b = s.get(Budget, bid)
            while b is not None and b.id not in seen:
                seen[b.id] = b
                b = s.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
        return list(seen.values())

    @staticmethod
    def latest_fx(s: Session) -> FxRate | None:
        return s.execute(select(FxRate).order_by(FxRate.created_at.desc()).limit(1)).scalar_one_or_none()

    @staticmethod
    def active_authorizations(s: Session, budget_ids: list[str]) -> list[SpendAuthorization]:
        now = datetime.now(UTC)
        rows = s.execute(select(SpendAuthorization).where(SpendAuthorization.scope_budget_id.in_(budget_ids),
                                                          SpendAuthorization.revoked.is_(False))).scalars()
        out = []
        for a in rows:
            exp = a.expires_at
            if exp is not None and exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp is None or exp > now:
                out.append(a)
        return out

    # ------------------------------------------------------------ ciclo da chamada
    def reserve(self, s: Session, call: LLMCall, budget_ids: list[str], estimate: CostEstimate,
                *, paid_provider: bool) -> None:
        """Deve ser chamado dentro de `db.write()` (BEGIN IMMEDIATE). Levanta exceção sem gravar nada."""
        if not estimate.safe:
            raise UnsafeEstimateError("; ".join(estimate.reasons) or "custo não estimável com segurança")
        if not budget_ids:
            raise BudgetError("nenhum orçamento aplicável à chamada")
        chain = self.chain(s, budget_ids)
        fx = self.latest_fx(s)
        if fx is None:
            if paid_provider or estimate.max_usd > 0:
                raise UnsafeEstimateError("câmbio USD→BRL não configurado")
            rate, margin, fx_id = Decimal(0), Decimal(0), None
        else:
            rate, margin, fx_id = D(fx.rate), D(fx.margin), fx.id
        max_brl = usd_to_brl(estimate.max_usd, rate, margin)

        if paid_provider:
            auths = self.active_authorizations(s, [b.id for b in chain])
            if not auths:
                raise SpendNotAuthorizedError("nenhuma autorização de gasto ativa para este orçamento")
            for a in auths:
                b = s.get(Budget, a.scope_budget_id)
                st = budget_status(s, b)
                if st.confirmed_brl + st.reserved_brl + max_brl > D(a.amount_brl):
                    raise SpendNotAuthorizedError(
                        f"autorização de R$ {a.amount_brl} insuficiente para a chamada (máx. R$ {q(max_brl)})")

        for b in chain:
            st = budget_status(s, b)
            if st.confirmed_brl + st.reserved_brl + max_brl > st.limit_brl:
                raise BudgetExceededError(
                    f"orçamento '{b.label}' insuficiente: disponível R$ {q(st.available_brl)}, "
                    f"necessário até R$ {q(max_brl)}")

        call.estimated_max_usd = q(estimate.max_usd)
        call.state = "RESERVED"
        s.add(call)
        s.flush()
        for b in chain:
            s.add(BudgetLedger(budget_id=b.id, llm_call_id=call.id, kind="RESERVE", amount_usd=q(estimate.max_usd),
                               amount_brl=q(max_brl), fx_rate_id=fx_id))

    def _reservations(self, s: Session, call_id: str) -> list[BudgetLedger]:
        return list(s.execute(select(BudgetLedger).where(BudgetLedger.llm_call_id == call_id,
                                                         BudgetLedger.kind == "RESERVE")).scalars())

    def _released(self, s: Session, call_id: str) -> bool:
        n = s.execute(select(func.count()).select_from(BudgetLedger).where(
            BudgetLedger.llm_call_id == call_id, BudgetLedger.kind == "RELEASE")).scalar_one()
        return n > 0

    def confirm(self, s: Session, call: LLMCall, actual_usd: Decimal) -> None:
        """Converte a reserva em gasto confirmado com o custo real."""
        if self._released(s, call.id):
            return
        for r in self._reservations(s, call.id):
            fx = s.get(FxRate, r.fx_rate_id) if r.fx_rate_id else None
            rate, margin = (D(fx.rate), D(fx.margin)) if fx else (ZERO, ZERO)
            s.add(BudgetLedger(budget_id=r.budget_id, llm_call_id=call.id, kind="RELEASE",
                               amount_usd=r.amount_usd, amount_brl=r.amount_brl, fx_rate_id=r.fx_rate_id))
            s.add(BudgetLedger(budget_id=r.budget_id, llm_call_id=call.id, kind="CONFIRM",
                               amount_usd=q(actual_usd), amount_brl=q(usd_to_brl(actual_usd, rate, margin)),
                               fx_rate_id=r.fx_rate_id))
        call.cost_usd = q(actual_usd)

    def release_unbilled(self, s: Session, call: LLMCall, reason: str) -> None:
        """Só quando há evidência de que nada foi cobrado (erro pré-geração)."""
        if self._released(s, call.id):
            return
        for r in self._reservations(s, call.id):
            s.add(BudgetLedger(budget_id=r.budget_id, llm_call_id=call.id, kind="RELEASE",
                               amount_usd=r.amount_usd, amount_brl=r.amount_brl, fx_rate_id=r.fx_rate_id,
                               note=reason))
        call.cost_usd = "0"

    def pending_reconciliation(self) -> list[dict]:
        with self.db.session() as s:
            rows = s.execute(select(LLMCall).where(LLMCall.state.in_(["UNCERTAIN", "FAILED_BILLED", "SENT"]),
                                                   LLMCall.cost_usd.is_(None))).scalars()
            return [{"id": c.id, "state": c.state, "requested_model": c.requested_model,
                     "generation_id": c.generation_id, "estimated_max_usd": c.estimated_max_usd} for c in rows]

    def manual_adjust(self, budget_id: str, amount_brl: str, author: str, note: str) -> None:
        with self.db.write() as s:
            s.add(BudgetLedger(budget_id=budget_id, kind="ADJUST", amount_usd="0", amount_brl=q(D(amount_brl)),
                               author=author, note=note))
