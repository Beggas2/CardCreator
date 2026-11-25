# ARCHITECTURE — CardFactory

## 1. Visão geral

Aplicação **local-first**, um único processo Python no Windows, com interface web servida em `127.0.0.1`. Sem microserviços, sem Redis, sem serviços pagos obrigatórios. Funciona integralmente com o provedor simulado e sem chave de API.

```
┌──────────────────────────── Navegador (localhost) ─────────────────────────────┐
│ React + TypeScript (Vite build estático)                                        │
│ Dashboard · Nova produção · Biblioteca · Mapa · Monitor · Mesa de revisão ·     │
│ Laboratório · Prompts · Exportação                                              │
└───────────────────────────────▲────────────────────────────────────────────────┘
                                │ HTTP JSON (+ SSE para progresso)
┌───────────────────────────────┴──── processo cardfactory (Python 3.12+) ───────┐
│ API (FastAPI)  ── comandos/consultas, nunca chama modelo diretamente           │
│ ORQ  Orquestrador: run → task graph; fila persistente em SQLite; workers async │
│ ├─ BIB  Biblioteca científica (fetch seguro, PDF, chunking, FTS5, evidências)  │
│ ├─ KB   Banco de conhecimento (entidades, objetivos, afirmações, cards, versões)│
│ ├─ PRM  Prompt Registry (políticas + papéis, versões imutáveis, cobertura)     │
│ ├─ GEN  Motor de geração (lotes, lease de objetivos, saída estruturada)        │
│ ├─ AUD  Motor de auditoria (científica, pedagógica, cobertura, segurança,      │
│ │        divergências, contradições, regressão, release gate)                  │
│ ├─ DEDUP Deduplicação em camadas                                               │
│ ├─ REN  Renderização determinística JSON → HTML Anki (função pura)             │
│ ├─ EXP  Importação/exportação (TSV V2.0, manifestos, validadores, round-trip)  │
│ ├─ EVAL Benchmark e avaliação cega                                             │
│ └─ FIN  Controle financeiro (estimativa, reserva atômica, reconciliação)       │
│ PROV Adaptadores: MockProvider · OpenRouterProvider · (futuros diretos)         │
│ SEC  transversal: segredos, sanitização, SSRF, limites, redação de logs        │
├────────────────────────────────────────────────────────────────────────────────┤
│ SQLite (WAL, Alembic) · data/blobs/ (documentos por hash) · data/exports/      │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Princípios que guiam o desenho

1. **Fatos de controle vêm do código.** Estados, contagens, custos, "validado", "testado", "importado" e citações são registros do banco. Texto do modelo nunca vira fato de controle (PRI-004).
2. **Conhecimento estruturado é a fonte primária.** Card = JSON versionado; HTML é derivado e reproduzível (TEC-015).
3. **Unidade de verificação é a afirmação**, não o card (SCI-013).
4. **Toda chamada paga passa por FIN antes de sair** e é registrada com prompt, modelo, provedor servido, tokens e custo (FIN-002, PRM-005).
5. **Nada destrutivo.** Não existe código de exclusão de notas; exclusões são manifestos (INT-005).
6. **Independência do auditor por construção**: o montador de contexto do auditor não tem acesso aos campos de autoavaliação do criador (AUD-001).
7. **Modos não implementados falham explicitamente** (`NOT_IMPLEMENTED`), nunca com implementação fictícia (E§30).

## 3. Módulos e responsabilidades

| Módulo | Pacote | Responsabilidade | Não faz |
|---|---|---|---|
| API | `cardfactory.api` | Rotas REST, validação Pydantic, SSE de progresso | Chamar modelos; regras de negócio |
| ORQ | `cardfactory.orchestrator` | Grafo de tarefas por modo, fila, workers, pausa/retomada, recuperação após crash, limites de tentativas | Conteúdo médico |
| PROV | `cardfactory.providers` | Interface `LLMProvider`; catálogo de modelos; chamadas; retry; truncamento; registro do modelo servido | Decidir orçamento (consulta FIN) |
| FIN | `cardfactory.finance` | Orçamentos hierárquicos, estimativa, reserva atômica, reconciliação, câmbio | Chamar provedores |
| PRM | `cardfactory.prompts` | Registry, composição de prompts por papel, cobertura de regras, hash | Alterar documentos normativos |
| BIB | `cardfactory.library` | Fontes, versões, documentos, seções, evidências, busca FTS5, fetch seguro, PDF | Decidir veracidade |
| KB | `cardfactory.knowledge` | Entidades, mapa, objetivos, afirmações, questões, cards, versões, operações | — |
| GEN | `cardfactory.generation` | Lotes, lease de objetivos, montagem de contexto, parse da saída | Renderizar HTML |
| AUD | `cardfactory.audit` | Passagens científicas, pedagógica, cobertura, segurança, divergência, regressão, gate | Corrigir sem operação registrada |
| DEDUP | `cardfactory.dedup` | Candidatos (hash, normalização, Jaccard, FTS, embeddings opcionais) e classificação | Excluir |
| REN | `cardfactory.rendering` | `render(card) -> (front_html, back_html)` puro; tokens visuais; contraste | Qualquer I/O |
| EXP | `cardfactory.exchange` | Importar exports legados, validar, serializar TSV/JSON, manifestos, round-trip, teste Anki descartável | Excluir/mover notas na coleção |
| EVAL | `cardfactory.evaluation` | Conjuntos dev/eval, fixtures adversariais, execução cega, métricas | Otimizar no conjunto de avaliação |
| SEC | `cardfactory.security` | Segredos, redação de logs, sanitização HTML, SSRF, limites de upload | — |

## 4. Fluxo de uma produção (modo Criação integral)

`inventário → pesquisa → recuperação documental → extração → mapa ideal → objetivos → [lease] geração em lotes → auditoria científica → auditoria pedagógica → auditoria de cobertura (mapa independente) → correções (≤2 por defeito) → reauditoria → deduplicação → validação técnica → revisão humana → exportação`

Detalhes de estados e transições em `PIPELINE.md`. Cada seta é uma ou mais tarefas persistidas; cada tarefa é idempotente pela sua chave.

## 5. Concorrência e persistência

- SQLite em modo WAL, `busy_timeout`, uma conexão por thread/tarefa; escrita curta e transacional.
- Fila = tabela `task` com `state`, `priority`, `not_before`, `lease_owner`, `lease_expires_at`. Workers são corrotinas asyncio no mesmo processo (padrão 4, configurável); chamadas HTTP são I/O-bound, então não há ganho em multiprocessamento.
- Reserva de orçamento e lease de objetivos usam `BEGIN IMMEDIATE` (lock de escrita do SQLite) para atomicidade.
- Na inicialização, tarefas `RUNNING` com lease expirado são reavaliadas: se a última chamada ao provedor está em estado `SENT` sem resposta, a tarefa vai para `UNCERTAIN` e passa por reconciliação antes de qualquer retry (PRV-007).

## 6. Provedores (resumo; detalhes em `docs/providers/OPENROUTER.md`)

- Interface única `LLMProvider.complete(request) -> LLMResult` e `catalog() -> list[ModelInfo]`.
- `MockProvider`: determinístico, roteirizável (sucesso, JSON inválido, truncamento, 429, 5xx, timeout, modelo servido diferente, custo), usado por todos os testes.
- `OpenRouterProvider`: Chat Completions (`POST /api/v1/chat/completions`), `response_format: json_schema` + `provider.require_parameters=true`; `provider.allow_fallbacks=false` e lista `models` vazia em etapas científicas críticas; custo lido de `usage.cost` e conferido em `GET /api/v1/generation?id=`; limite da chave lido em `GET /api/v1/key`.
- Batch (`/api/v1/batches`, ~50% do preço) previsto apenas para etapas sem pesquisa web; não entra no MVP.

## 7. Segurança (resumo; detalhes em `SECURITY.md`)

Bind exclusivo em 127.0.0.1; chave em variável de ambiente ou Windows Credential Manager (`keyring`); redação de segredos em logs; HTML de modelos e de fontes nunca é renderizado sem passar pelo sanitizador allowlist; fetch com bloqueio de IPs privados/loopback e limites de tamanho/tempo; conteúdo externo sempre delimitado como dado não confiável nos prompts e sem acesso a ferramentas que alterem estado.

## 8. Instalação no Windows (alvo)

`uv` gerencia Python e dependências; `cardfactory.cmd` (ou `start.ps1`) executa `uv run cardfactory serve`, abre o navegador em `http://127.0.0.1:8765`. O frontend vem pré-compilado no pacote; Node só é necessário para desenvolvimento da UI.

## 9. Estrutura do repositório

```
CardCreator/
├─ README.md  AGENTS.md  ARCHITECTURE.md  REQUIREMENTS.md  REQUIREMENTS_TRACEABILITY.md
├─ DATA_MODEL.md  PIPELINE.md  PROMPT_REGISTRY.md  QUALITY_POLICY.md  BENCHMARK_PROTOCOL.md
├─ COST_CONTROL.md  SECURITY.md  IMPLEMENTATION_PLAN.md  STATUS.md  CONTRACTS.md
├─ docs/
│  ├─ normative/            # Prompt Criação.txt, Prompt Revisor.txt (byte a byte) + SHA256SUMS
│  ├─ spec/                 # especificação CardFactory original do proprietário
│  ├─ adr/                  # ADR-0001 … decisões
│  └─ providers/OPENROUTER.md
├─ requirements/            # build_matrix.py, requirements.csv, REGRESSION_MAP.md
├─ backend/
│  ├─ pyproject.toml  alembic/  src/cardfactory/<módulos>  tests/{unit,integration,regression,adversarial}
├─ frontend/                # Vite + React + TS; tests e2e Playwright
├─ prompts/                 # políticas e papéis (fonte versionada, importada no Registry)
├─ fixtures/                # cards de referência, defeitos conhecidos, respostas simuladas
├─ .env.example  .gitattributes  .gitignore
```

## 10. Decisões arquiteturais (ADRs)

| ADR | Decisão | Motivo |
|---|---|---|
| 0001 | Monólito modular local em um processo (FastAPI + workers asyncio + SQLite WAL) | Requisito local-first/Windows; menor complexidade operacional; concorrência é I/O-bound |
| 0002 | SQLAlchemy 2 + Alembic; IDs ULID texto | Migrações confiáveis; ids ordenáveis e estáveis entre exportações |
| 0003 | Hierarquia de prioridades do Revisor como canônica | Superconjunto compatível (ver REQUIREMENTS §3) |
| 0004 | Enums unificados de cobertura/operação/dimensões | Resolver AMB-03/04/05 com tabela de equivalência |
| 0005 | Renderizador único em Python; preview da UI pede HTML ao backend | O preview mostra exatamente o que será exportado |
| 0006 | Negrito derivado de `retrieval_target`, cor derivada de `semantic` | Separar alvo de recuperação de natureza semântica (AMB-06) |
| 0007 | OpenRouter via Chat Completions, não Responses API | Contrato mais estável e portável para outros provedores; ambos suportados oficialmente |
| 0008 | Validação JSON Schema local sempre, mesmo com `strict` | A documentação diz que alguns provedores tratam o schema como dica |
| 0009 | Sem retry automático de chamada em estado incerto | OpenRouter não documenta chave de idempotência e requisições não-streaming continuam sendo cobradas após abort |
| 0010 | Custos em `Decimal`; USD original + BRL com taxa datada | Evitar erro de ponto flutuante; rastrear câmbio |
| 0011 | FTS5 primeiro; embeddings locais só se o benchmark de deduplicação/recuperação justificar | Evitar dependência pesada sem evidência de ganho |
| 0012 | Teste de importação com o pacote `anki` em coleção temporária | Permite afirmar "importação testada" de forma verdadeira |

Os ADRs serão gravados individualmente em `docs/adr/` no primeiro commit.
