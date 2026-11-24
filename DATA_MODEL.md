# DATA_MODEL — Modelo relacional (SQLite)

Convenções: chaves primárias `id TEXT` (ULID); `created_at`/`updated_at` em UTC ISO-8601; valores monetários em `TEXT` decimal (lidos como `Decimal`); JSON em colunas `TEXT` validadas por Pydantic; tabelas marcadas **[append-only]** nunca recebem UPDATE de conteúdo (só inserções), garantindo histórico não retroativo.

Um grafo de conhecimento sofisticado não é necessário no MVP: as relações abaixo cobrem a propagação "diretriz alterada → afirmações → cards" com duas junções.

## 1. Organização

| Tabela | Campos principais | Notas |
|---|---|---|
| `project` | name, area, description, pedagogical_profile_id, deck_prefix (padrão `IGOR::`), default_notetype | Um projeto = uma área/coleção |
| `pedagogical_profile` [append-only por versão] | name, version, content_json, hash | PRI-006 |
| `production` | project_id, mode (`CREATE_FULL`, `EXPAND`, `AUDIT_FULL`, …), theme, scope_json, depth, target_cards, research_mode (`AUTONOMOUS`/`DOCUMENTS`/`HYBRID`), batch_size, concurrency, state | Configuração de "Nova produção" |
| `stage_model_config` | production_id, stage, model_id, provider_routing_json, reasoning_json, fallback_policy (`NONE`/`ALLOWED_RECORDED`), max_tokens | PRV-003, PRV-008 |

## 2. Biblioteca científica

| Tabela | Campos principais | Notas |
|---|---|---|
| `source` | title_confirmed, institution, source_tier (`BR_OFFICIAL`, `BR_SOCIETY`, `INTL_SOCIETY`, `SYSTEMATIC_REVIEW`, `PRIMARY_STUDY`, `SECONDARY_CLINICAL`, `NOT_ACCEPTED`), doc_type, doi, url, license, rights_status | Identidade lógica de um documento (ex.: "PCDT X") |
| `source_version` | source_id, version_label, published_at, page_updated_at, effective_from, effective_to, validity_status (`CURRENT`, `SUPERSEDED`, `REVOKED`, `UNCERTAIN`), supersedes_version_id, population, context | MNT-001; datas separadas (SCI-007) |
| `document` | source_version_id, access_state (`FOUND`, `RETRIEVED`, `PARTIALLY_READ`, `VERIFIED`, `UNAVAILABLE`, `OUTDATED`, `VALIDITY_UNCERTAIN`), content_hash (SHA-256), blob_path, mime, pages, accessed_at, fetch_url | BIB-003 |
| `document_section` | document_id, path (ex.: "4.2 > Tabela 3"), kind (`TEXT`, `TABLE`, `ALGORITHM`, `FOOTNOTE`), page_from, page_to, text, parse_quality (`OK`, `UNCERTAIN`, `FAILED`) | tabela não interpretável → pendência (BIB-004) |
| `document_section_fts` | FTS5 virtual sobre section.text | Busca textual |
| `evidence_span` | section_id, quote (trecho autorizado, curto), char_start, char_end, retrieved_via (`DOCUMENT`, `SEARCH_SNIPPET`, `USER_UPLOAD`) | `SEARCH_SNIPPET` não confirma claim crítica (SCI-023) |
| `research_query` | production_id, query, engine, filters_json, result_json, cost_call_id, cache_key | Cache de pesquisa (BIB-006) |

## 3. Conhecimento

| Tabela | Campos principais | Notas |
|---|---|---|
| `clinical_entity` | project_id, name, synonyms_json, home_deck_path | Propriedade do conhecimento (COV-015) |
| `map_dimension` | entity_id, dimension_code (1–57), state (`APPLICABLE_COVERED`, `APPLICABLE_PENDING`, `NOT_APPLICABLE`, `COVERED_ELSEWHERE`, `NOT_VERIFIABLE`), justification, map_origin (`CREATOR`, `INDEPENDENT`) | Dois mapas comparáveis (COV-013) |
| `decision_point` | entity_id, description, condition_axis (ex.: `STABLE_UNSTABLE`), disposition_relevant | COV-006 |
| `learning_objective` | entity_id, subtopic, knowledge_type, knowledge_level (`FACTUAL`/`UNDERSTANDING`/`APPLICATION`), description, clinical_relevance, exam_relevance, purpose, necessity (`REQUIRED`/`RECOMMENDED`/`OPTIONAL`/`UNNECESSARY`), coverage_state (9 estados R§14.1), lease_owner, lease_expires_at | COV-003/004, TEC-017 |
| `objective_dependency` | objective_id, depends_on_id | |
| `claim` | objective_id, card_version_id (nullable), text, component (`INDICATION`, `DOSE`, `ROUTE`, `INTERVAL`, `DURATION`, `CONTRAINDICATION`, `POPULATION`, `MECHANISM`, `CRITERION`, `CUTOFF`, `CONDUCT`, `DISPOSITION`, `OTHER`), population, scenario, criticality (`CRITICAL`, `HIGH`, `NORMAL`), negation_kind (nullable: `ABSOLUTE_CI`, `RELATIVE_CI`, `NO_INDICATION`, `RECOMMENDED_AGAINST`, `INSUFFICIENT_EVIDENCE`, `INDIVIDUALIZE`), numeric_json (valor, operador, unidade) | Afirmação atômica (SCI-013) |
| `claim_evidence` | claim_id, evidence_span_id, supports (`SUPPORTS`, `CONTRADICTS`, `PARTIAL`, `CONTEXT_ONLY`) | Fonte sustenta a afirmação exata |
| `claim_verdict` [append-only] | claim_id, audit_id, verdict (9 classes R§10.1), rationale, evidence_ids_json | Histórico de verificações |
| `divergence` | claim_ids_json, cause (`POPULATION`, `SCENARIO`, `RESOURCES`, `TEMPORAL`, `METHOD`, `EVIDENCE_STRENGTH`, `CONDITIONAL`, `REGULATORY`, `TRUE_DISAGREEMENT`), resolution (`BR_PRIMARY_COMMENT`, `COMPARISON_CARD`, `HUMAN_DECISION`, `OPEN`), notes | SCI-008 |
| `question` | exam_board, year, institution, exam, number, stem (se autorizado), options_json, key_preliminary, key_final, annulled, source, split (`PLANNING`/`EVALUATION`) | QST-001, QST-008 |
| `question_requirement` | question_id, objective_id, step (`INTERPRET`, `RECOGNIZE`, `CLASSIFY`, `SELECT`, `ELIMINATE`), coverage_state | |

## 4. Cards, versões e operações

| Tabela | Campos principais | Notas |
|---|---|---|
| `card` | project_id, card_key (id interno estável, imutável), anki_guid (nullable, UNIQUE por projeto), notetype, state (máquina E§27), quarantine (bool), origin (`GENERATED`, `IMPORTED`) | Identidade (INT-001) |
| `card_version` [append-only] | card_id, version_no, schema_version, content_json (contrato `card.v2`), deck_path, tags_json, cognitive_type (A–L), layout, didactic_order, author_type (`AI`/`HUMAN`/`IMPORT`), created_by_call_id, objective_change (`EQUIVALENT`/`SUBSTANTIAL`), content_hash | Rollback = nova versão apontando para conteúdo antigo |
| `card_objective` | card_version_id, objective_id, role (`PRIMARY`/`SECONDARY`) | |
| `rendered_artifact` | card_version_id, renderer_version, front_html, back_html, html_hash | Derivado e reproduzível |
| `operation` [append-only] | card_id, kind (12 operações R§37), from_version_id, to_version_id, related_card_ids_json, justification, status (`PROPOSED`, `APPLIED`, `REJECTED`, `AWAITING_HUMAN`), defect_ids_json | Manifestos derivam daqui |
| `media_asset` | card_id, kind, finding, desired_source, purpose, status (`PENDING`, `OBTAINED`, `REJECTED`), file_path, license | VIS-016 |

## 5. Auditoria, defeitos e revisão humana

| Tabela | Campos principais | Notas |
|---|---|---|
| `audit` [append-only] | card_version_id (ou production_id para auditorias globais), kind (`SCI_FACTS`, `SCI_NUMBERS`, `SCI_PHARMA`, `SCI_CONDUCT`, `SCI_CONTRAINDICATION`, `SCI_POPULATIONS`, `SCI_TEMPORAL`, `SCI_DIVERGENCE`, `SCI_CONTRADICTION`, `SCI_TRACEABILITY`, `PEDAGOGICAL`, `COVERAGE`, `SECURITY`, `TECHNICAL`, `VISUAL`, `REGRESSION`), llm_call_id, result_json, context_manifest_json | `context_manifest` prova o que o auditor recebeu (AUD-001) |
| `defect` | card_id, audit_id, category (19 de R§36.1), severity (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `OBSERVATION`), description, evidence_ids_json, status (`OPEN`, `FIXED`, `JUSTIFIED`, `ESCALATED`), correction_attempts | AUD-007/009 |
| `validation_finding` | card_version_id/export_run_id, code, level (`ERROR`/`WARNING`), message, status (`OPEN`, `FIXED`, `JUSTIFIED`), justification | Saída dos validadores determinísticos |
| `human_review` [append-only] | card_version_id, reviewer, decision (`APPROVE`, `REJECT`, `EDIT`, `REQUEST_RESEARCH`, `REQUEST_FIX`, `QUARANTINE`), reasons_json (tipologia E§26), duration_seconds | Separado de aprovação automática (APR-004) |
| `editorial_decision` | human_review_id, kind, example_before, example_after, reusable (bool) | Aprendizado editorial (MNT-003) |
| `regression_case` | origin (`C40`, `R54`, `NEW`), code, description, fixture_path, test_name | REG-* |
| `verdict` | production_id, target (`ORIGINAL`/`CORRECTED`), dimension, status | Dimensões independentes (AUD-014) |

## 6. Orquestração

| Tabela | Campos principais |
|---|---|
| `run` | production_id, mode, state (`PENDING`, `RUNNING`, `PAUSED`, `PAUSED_BUDGET`, `CANCELLED`, `COMPLETED`, `FAILED`), started_at, finished_at |
| `batch` | run_id, stage, objective_ids_json, card_ids_json, size, state |
| `task` | run_id, batch_id, stage, kind, state (`PENDING`, `READY`, `RUNNING`, `SUCCEEDED`, `FAILED`, `UNCERTAIN`, `CANCELLED`, `SKIPPED_REUSED`, `AWAITING_HUMAN`), priority, input_json, output_json, attempts, max_attempts, last_error, idempotency_key (UNIQUE), checkpoint_json, lease_owner, lease_expires_at, not_before, started_at, finished_at |
| `task_dependency` | task_id, depends_on_task_id |

## 7. Provedores, prompts e custos

| Tabela | Campos principais | Notas |
|---|---|---|
| `model_catalog` | provider, model_id, name, pricing_json (como recebido), context_length, max_completion_tokens, supported_parameters_json, input_modalities_json, fetched_at | Snapshot por sincronização; nunca hardcoded |
| `prompt` | role (`RESEARCHER`, `EXTRACTOR`, `PLANNER`, `CREATOR`, `AUDITOR_SCI`, `AUDITOR_PED`, `AUDITOR_COV`, `AUDITOR_SEC`, `RESOLVER`, `CLASSIFIER`, `CONTRADICTION`, `COMPARATOR`) ou policy (`POLICY_SCI`, `POLICY_PED`, `POLICY_VIS`, `POLICY_INT`) | |
| `prompt_version` [append-only] | prompt_id, version, body, req_ids_json, parent_version_id, hash, created_by, note | Imutável (PRM-005) |
| `llm_call` [append-only + campos de reconciliação] | task_id, provider, requested_model, served_model, served_provider, prompt_version_ids_json, prompt_hash, request_hash, idempotency_key, state (`RESERVED`, `SENT`, `SUCCEEDED`, `FAILED_BILLED`, `FAILED_UNBILLED`, `UNCERTAIN`, `RECONCILED`), finish_reason, tokens_in, tokens_out, tokens_cached, tokens_reasoning, cost_usd, generation_id, latency_ms, error_json | |
| `budget` | scope (`PROJECT`, `RUN`, `STAGE`, `MODEL`, `BATCH`, `EXPERIMENT`), scope_ref, limit_brl, parent_budget_id | Hierarquia (FIN-001) |
| `budget_ledger` [append-only] | budget_id, llm_call_id, kind (`RESERVE`, `RELEASE`, `CONFIRM`, `ADJUST`), amount_usd, amount_brl, fx_rate_id | Saldo = soma do ledger |
| `fx_rate` | currency_pair, rate, source, valid_on | FIN-006 |
| `spend_authorization` | scope, amount_brl, granted_by, granted_at, expires_at, note | Nenhuma chamada real sem autorização ativa (FIN-012) |

## 8. Exportação

| Tabela | Campos principais |
|---|---|
| `export_run` | production_id, mode, format (`TSV_GUID`, `TSV_NO_GUID`, `SIMPLE`, `JSON`, `IGORSRS_V0`), version_label, files_json (nome, hash, contagem), round_trip_ok, import_tested (`NOT_TESTED`, `PASSED`, `FAILED`), previous_export_id, diff_json |

## 9. Consultas-chave garantidas pelo modelo

- **Impacto de mudança de diretriz**: `source_version → document → section → evidence_span → claim_evidence → claim → card_version → card` (MNT-001).
- **Cobertura com denominador**: `learning_objective` agrupado por `coverage_state` (COV-005).
- **Gate de liberação**: card bloqueado se existir `defect` crítico aberto, `claim` crítica sem `claim_verdict=CONFIRMADA` vigente, `validation_finding` ERROR aberto ou `human_review` ausente quando exigido (APR-002).
- **Custo por card aprovado**: `llm_call.cost` atribuído via task → batch → cards / cards com `human_review=APPROVE` (FIN-009).
