# CONTRACTS — Contratos entre módulos

Todos os contratos são modelos Pydantic versionados em `cardfactory.contracts`, exportados como JSON Schema em `contracts/schemas/*.json`. Uma mudança incompatível incrementa a versão maior; registros antigos permanecem legíveis.

## 1. `card.v2` — representação estruturada do card (refina o exemplo conceitual de E§11 / C§33)

```json
{
  "schema_version": "2.1",
  "card_key": "01JD7Z…",                     // id interno estável (imutável)
  "anki_guid": null,                         // GUID real; null para nota nova
  "objective_ids": ["obj_…"],
  "deck_path": ["IGOR", "Cardiologia", "SCA", "IAMCSST"],
  "cognitive_type": "C",                     // A..L (12 tipos)
  "layout": "criteria",                      // direct | list | criteria | comparison | score | mechanism | algorithm | pharmacology | case | negative | image | integration
  "front": {
    "segments": [ { "text": "Quais critérios …?", "emphasis": "retrieval_object" } ],
    "align": "auto"                          // auto | center | left (renderer decide se auto)
  },
  "minimal_answer": "texto curto do mínimo verificável",
  "answer": [
    {
      "role": "essential",                   // essential | understanding | complement
      "block": "list",                       // paragraph | list | ordered_list | table | comparison | sequence | formula
      "title": null,
      "items": [
        { "segments": [
            { "text": "Supradesnivelamento de ST", "semantic": "concept", "retrieval_target": true, "claim_ids": ["clm_1"] },
            { "text": " ≥ 1 mm", "semantic": "value", "retrieval_target": true, "claim_ids": ["clm_2"] },
            { "text": " em duas derivações contíguas", "semantic": "neutral", "retrieval_target": false, "claim_ids": ["clm_2"] }
        ] }
      ],
      "combination_rule": "all"              // obrigatório em critérios: all | any | at_least_n | major_minor | mutually_exclusive | null
    }
  ],
  "short_reference": { "source_ids": ["src_…"], "display": "SBC, 2025" },   // quando normativo/controverso/temporal
  "tags": ["cardiologia::sca", "criterio"],
  "claims": [ { "claim_id": "clm_1", "text": "…", "component": "CRITERION", "criticality": "HIGH", "population": "adultos" } ],
  "limitations": [],                         // obrigatório (pode ser vazio)
  "validation_status": "pending"
}
```

Regras do schema (determinísticas):
- `semantic ∈ {concept, conduct, diagnosis, value, risk, neutral, complement, reference, divergence}`; cor é derivada pelo renderer (VIS-003). O modelo **nunca** envia cor, CSS ou HTML.
- `segments[].text` é texto puro; qualquer `<`, `>`, `&` é escapado pelo renderer. Tags HTML vindas do modelo são rejeitadas.
- Existe ≥1 bloco `essential`; blocos são reordenados essencial → compreensão → complemento.
- `retrieval_target=true` não é permitido em blocos `complement` (PED-004).
- Bloco `criteria` exige `combination_rule` (C§19.2).
- Sem campos de confiança numérica (AUD-006).

Refinamentos da Fase 3 (schema em `backend/src/cardfactory/contracts/schemas.py`):
- O modelo emite `CARD_V2_MODEL`; o sistema acrescenta `schema_version`, `card_key`, `anki_guid`, `images` e `validation_status`.
- Segmentos têm `italic` (só nomenclatura científica, termos estrangeiros e convenções, C§18.3).
- Itens têm `segments` (blocos de texto) ou `cells` (linhas de `table`/`comparison`); blocos tabulares têm `header` opcional.
- Regra de combinação: `combination_rule` + `combination_n` (para `at_least_n`) + `combination_text` (obrigatório em `major_minor`). O renderizador mostra a regra no bloco.
- Cada card traz `evidence_span_ids` e `media_requests`; mídia só vira `images` depois de obtida com direitos verificados (VIS-016).
- `generation_batch.v1` = `{cards: [card.v2], unverified_claims: [{text, objective_id, reason}], limitations}`.
- Exportação: notas novas vão com GUID vazio (testado no Anki 26.09: o Anki gera o GUID) e recebem a tag `cf::<card_key>` para reconciliação.

## 2. Saídas dos papéis de IA

| Papel | Contrato de saída | Campos essenciais |
|---|---|---|
| Pesquisador | `research_result.v1` | candidatos [{title_claimed, institution, url, doc_type, year_claimed, why_relevant}], buscas realizadas, limitações. **Não confirma nada**: confirmação é do BIB após recuperar o documento |
| Extrator | `extraction.v1` | por seção: afirmações candidatas com trecho literal (offsets), população, condições, notas de rodapé associadas, tabelas com `parse_quality` |
| Planejador | `plan.v1` | entidades, 57 dimensões com estado, pontos de decisão, objetivos (todos os campos de COV-003), dependências, subdecks, quantidade proposta por objetivo com justificativa |
| Criador | `generation_batch.v1` | lista de `card.v2` + para cada card: objective_ids, claims, evidence_span_ids usados, `limitations` |
| Auditor científico | `sci_audit.v1` | por claim: verdict (9 classes), evidence_span_ids, rationale, `needs_more_evidence`; defeitos {category, severity, description} |
| Auditor pedagógico | `ped_audit.v1` | achados por dimensão (17), defeitos, operação proposta (KEEP por padrão) e diff mínimo sugerido |
| Auditor de cobertura | `cov_audit.v1` | mapa independente, diff com mapa do criador, estados por objetivo, lacunas classificadas, autossuficiência (28 perguntas) |
| Auditor de segurança | `sec_audit.v1` | sinais de injeção, conteúdo de terceiros, dados pessoais, direitos |
| Resolvedor | `resolution.v1` | causa da divergência, versões concorrentes, recomendação, `requires_human` |
| Classificador | `classification.v1` | entidade, deck, tags, tipo cognitivo, nível |
| Detector de contradições | `contradiction.v1` | pares, SimilarityKind, população/cenário de cada lado |
| Avaliador comparativo | `comparison.v1` | preferências cegas por critério com justificativa; sem pontuação agregada |

Todo contrato de IA inclui `limitations: [string]` e é validado localmente (ADR-0008). Resposta inválida → até 1 tentativa de reparo com o erro de validação (custo reservado), depois `FAILED`.

## 3. Provedor

```python
class LLMRequest(BaseModel):
    task_id: str
    stage: Stage
    model_id: str
    messages: list[Message]            # conteúdo externo marcado como untrusted
    response_schema: dict | None
    max_output_tokens: int
    reasoning: ReasoningConfig | None
    web_search: WebSearchConfig | None
    files: list[FileRef] = []
    routing: RoutingPolicy             # allow_fallbacks, require_parameters, order/only, data_collection
    idempotency_key: str
    timeout_s: float

class LLMResult(BaseModel):
    status: Literal["ok", "truncated", "invalid_output", "error", "uncertain"]
    served_model: str | None
    served_provider: str | None
    generation_id: str | None
    output_text: str | None
    parsed: dict | None
    finish_reason: str | None
    usage: Usage                       # tokens in/out/cached/reasoning, cost_usd (Decimal | None)
    citations: list[Citation]
    error: ProviderError | None        # classe: transient | rate_limited | permanent | billing | uncertain

class LLMProvider(Protocol):
    name: str
    async def catalog(self) -> list[ModelInfo]: ...
    async def complete(self, req: LLMRequest) -> LLMResult: ...
    async def lookup_cost(self, generation_id: str) -> CostRecord | None: ...
    async def key_status(self) -> KeyStatus | None: ...
```

## 4. Finanças

```python
class CostEstimate(BaseModel):  max_usd: Decimal; expected_usd: Decimal; basis: dict; safe: bool
def reserve(scopes: list[BudgetRef], estimate: CostEstimate, call_id: str) -> Reservation  # atômico; levanta BudgetExceeded
def confirm(call_id: str, actual_usd: Decimal | None) -> None   # None → fica pendente de reconciliação
def release(call_id: str) -> None                              # só quando comprovadamente não cobrado
```

## 5. Orquestrador ↔ módulos

Cada etapa implementa `StageHandler.plan(run) -> list[TaskSpec]` e `StageHandler.execute(task, ctx) -> TaskOutput`. `ctx` dá acesso a KB, BIB, PRM, FIN e ao provedor, e registra checkpoints. Handlers não abrem transações longas e não chamam o provedor sem `ctx.llm(...)` (que aplica FIN e registro).

## 6. Exportação / integração

- `anki_tsv_v2`: formato principal C§31.1 (6 colunas, cabeçalhos fixos).
- `anki_tsv_noguid`: R§43.3. `anki_simple`: `Frente;Verso`.
- `manifest.v1` (JSON): operações, movimentações, exclusões propostas, pendências, fontes, mídia, contagens reconciliadas, hash de cada arquivo.
- `igorsrs_export.v0`: **reservado**. Será definido com o proprietário; não altera o IgorSRS.
