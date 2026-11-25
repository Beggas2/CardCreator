# IMPLEMENTATION_PLAN — Plano de implementação

Regras: cada fase termina com registro em `STATUS.md` (implementado, testado de fato, resultados, limitações, pendências, decisões, próxima etapa, custos). Nenhuma chamada paga até a Fase 6, e só com autorização. Nenhuma funcionalidade fictícia: o que não estiver pronto retorna `NOT_IMPLEMENTED` explícito.

## Fase 0 — Especificação e arquitetura (esta entrega)

Entregues: leitura integral; `REQUIREMENTS_TRACEABILITY.md` (221 requisitos); `REGRESSION_MAP.md` (146 falhas históricas); `REQUIREMENTS.md` (hierarquia + 16 ambiguidades); `ARCHITECTURE.md` (+12 ADRs); `DATA_MODEL.md`; `CONTRACTS.md`; `docs/providers/OPENROUTER.md`; `COST_CONTROL.md`; `BENCHMARK_PROTOCOL.md`; este plano.
Aceite: proprietário revisa e responde AMB-01, AMB-02, AMB-06 e o plano.

## Fase 1 — Fundação (sem gasto)

Etapas verificáveis, cada uma com testes:

1. **Repositório**: estrutura, `pyproject` (uv), Ruff, mypy, pytest; `docs/normative/` byte a byte + `.gitattributes` + `test_normative_docs_hash`; especificação original em `docs/spec/`; ADRs; `.env.example`; CI GitHub Actions só com mock.
2. **Banco**: SQLAlchemy + Alembic, WAL, todas as tabelas de organização, orquestração, provedores, prompts, finanças e cards/versões (as demais entram nas fases 2–4 por migração).
3. **Provedor simulado** roteirizável + interface `LLMProvider` + testes de contrato.
4. **Finanças**: orçamentos hierárquicos, estimativa, reserva atômica, ledger, reconciliação, câmbio, autorização de gasto, pausa por orçamento.
5. **Adaptador OpenRouter** (implementado e testado só com respostas gravadas/mocks HTTP): catálogo, chat estruturado, erros, retry/backoff/jitter, 429, truncamento, modelo servido, custo, `/generation`, `/key`. Chamada real bloqueada sem autorização.
6. **Prompt Registry**: políticas e papéis versionados com `req_ids`, hash, verificação de cobertura de regras obrigatórias por papel.
7. **Orquestrador**: run/task/dependências, workers asyncio, lease, idempotência, pausa/retomada/cancelamento, recuperação após kill, tarefas `UNCERTAIN`.
8. **Segurança base**: segredos (env/keyring), redação de logs, bind localhost, teste de vazamento.
9. **Interface inicial**: React/Vite dark-first com Dashboard (dados reais do banco), Monitor de execução, Editor de prompts (ver/duplicar/comparar/restaurar) e tela de Orçamento; build servido pelo FastAPI; Playwright smoke.
10. **Pipeline de ponta a ponta com mock**: execução fictícia de "criação integral" com mocks percorrendo todas as etapas (handlers de geração/auditoria ainda simples, mas reais em persistência, custo e estados), provando retomada e orçamento.

Aceite: `pytest` verde sem rede; teste de crash/retomada; teste de concorrência no orçamento; nenhum segredo em logs; app inicia no Windows com um comando (verificação manual pelo proprietário, ou em runner Windows na CI).

## Fase 2 — Pesquisa e conhecimento
Biblioteca (fontes, versões, documentos, seções, FTS5, evidências), fetch seguro (SSRF), PDF local, importação de export Anki legado com validação inicial, importação de questões com splits, entidades, mapa ideal (57 dimensões), objetivos, pontos de decisão, papéis pesquisador/extrator/planejador (testados com mock).

## Fase 3 — Geração e renderização
Contrato `card.v2`, geração em lotes com lease, renderizador determinístico dos 12 tipos, preview (desktop/celular/escuro/claro), versionamento e rollback, validadores (C§38/R§45), serializadores TSV (3 formatos), round-trip, teste de importação com `anki` em coleção descartável, manifestos, regressões tipo U.

## Fase 4 — Auditoria
Passagens científicas, cálculo dimensional, auditor pedagógico, mapa independente e cobertura, segurança, divergências/contradições, deduplicação em camadas, operações e correção com limite, reauditoria, quarentena, estado final simulado, regressão, gate de liberação, relatórios com contagens do banco.

## Fase 5 — Revisão e benchmark
Mesa de revisão (teclado, filtros, versões, evidências, desfazer), aprovação humana distinta, aprendizado editorial, Laboratório de modelos com avaliação cega, conjuntos dev/eval, fixtures adversariais completas, métricas.

## Fase 6 — Experimento (somente com autorização financeira)
Etapa 1 microbenchmark (R$15) → Etapa 2 ~50 cards → Etapa 3 ~200 → Etapa 4 até ~1.000 úteis, cada avanço condicionado aos critérios de `BENCHMARK_PROTOCOL.md` §6 e à aprovação do proprietário.

## Riscos principais

| Risco | Mitigação |
|---|---|
| R$100 insuficiente para 1.000 cards com auditoria independente | Medir custo por card aprovado no benchmark; ajustar quantidade, nunca qualidade |
| Auditor de IA não detecta erros sutis | Conjunto de defeitos plantados; revisão humana de 100% do lote experimental |
| Fontes brasileiras em PDF escaneado ou atrás de paywall | Pendência explícita; upload do proprietário; OCR pago seletivo |
| Mudanças na API do OpenRouter | Adaptador isolado; revisão da documentação a cada 30 dias; testes de contrato |
| Escopo muito grande para um MVP | Prioridade P0/P1 da matriz; modos não-MVP só com arquitetura |
