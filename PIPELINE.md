# PIPELINE — Etapas, tarefas e estados

## Etapas (E§21) e modos

| # | Etapa (`Stage`) | Criação integral | Expansão | Auditoria integral | Usa IA | Paga |
|---|---|---|---|---|---|---|
| 1 | INVENTORY — inventário de materiais e coleção | ✓ | ✓ | ✓ | não* | não |
| 2 | RESEARCH — pesquisa de fontes | ✓ | ✓ | ✓ | sim | sim |
| 3 | RETRIEVAL — recuperação documental | ✓ | ✓ | ✓ | não | não** |
| 4 | EXTRACTION — extração de afirmações e seções | ✓ | ✓ | ✓ | sim | sim |
| 5 | PLANNING — mapa ideal, entidades, subdecks | ✓ | ✓ | ✓ (independente) | sim | sim |
| 6 | OBJECTIVES — matriz de objetivos | ✓ | ✓ | ✓ | sim | sim |
| 7 | GENERATION — lotes com lease de objetivos | ✓ | ✓ (só lacunas) | (só correções/CREATE) | sim | sim |
| 8 | AUDIT_SCI — passagens científicas | ✓ | ✓ | ✓ | sim | sim |
| 9 | AUDIT_PED | ✓ | ✓ | ✓ | sim | sim |
| 10 | AUDIT_COV — mapa independente, autossuficiência | ✓ | ✓ | ✓ | sim | sim |
| 11 | CORRECTION — operações (≤2 por defeito) | ✓ | ✓ | ✓ | sim | sim |
| 12 | REAUDIT — versões modificadas | ✓ | ✓ | ✓ | sim | sim |
| 13 | DEDUP — candidatos + classificação | ✓ | ✓ | ✓ | parcial | parcial |
| 14 | TECH_VALIDATION — validadores, round-trip, Anki | ✓ | ✓ | ✓ | não | não |
| 15 | HUMAN_REVIEW | ✓ | ✓ | ✓ | não | não |
| 16 | EXPORT | ✓ | ✓ | ✓ | não | não |

\* classificação de entidades de um export pode usar IA. \** OCR pago opcional.

Demais modos (Atualização científica, Reformatação, Reconstrução, Complementação por provas; Auditorias B–I) têm grafo declarado e retornam `NOT_IMPLEMENTED` até serem implementados.

## Estados de tarefa

`PENDING → READY → RUNNING → SUCCEEDED | FAILED | UNCERTAIN | CANCELLED | AWAITING_HUMAN | SKIPPED_REUSED`

- `READY` quando todas as dependências estão `SUCCEEDED`/`SKIPPED_REUSED`.
- `FAILED` com tentativas restantes volta a `READY` com `not_before = agora + backoff`.
- `UNCERTAIN` nunca é reexecutada automaticamente; exige reconciliação (custo) e decisão.
- Reprocessar etapa/lote/card cria **novas** tarefas; as antigas permanecem no histórico.

## Estados do card (E§27)

`DRAFT → GENERATED → IN_AUDIT → (CORRECTED → IN_AUDIT)* → AUTO_APPROVED → PENDING_HUMAN → HUMAN_APPROVED → READY_FOR_EXPORT → COMMERCIALLY_RELEASED`
com saídas laterais `REJECTED`, `QUARANTINE`, `OUTDATED`. `HUMAN_APPROVED` exige registro em `human_review`; `COMMERCIALLY_RELEASED` exige `release_gate` sem bloqueios.

## Estados de execução

`PENDING → RUNNING ⇄ PAUSED`, `RUNNING → PAUSED_BUDGET` (orçamento), `→ CANCELLED | COMPLETED | FAILED`. Uma execução só é `COMPLETED` sem tarefas obrigatórias pendentes (ORQ-005).
