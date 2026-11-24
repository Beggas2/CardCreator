# STATUS

## Fase 1 — concluída (24/11/2026)

- **Implementado**:
  - Backend Python (FastAPI, SQLAlchemy, Alembic) com SQLite em WAL e transações `BEGIN IMMEDIATE`.
  - Controle financeiro: orçamentos hierárquicos, razão append-only, reserva atômica, câmbio com margem, autorização de gasto obrigatória para provedores pagos, reconciliação.
  - Provedores: interface comum, simulado roteirizável e adaptador OpenRouter (catálogo, chat estruturado, classificação de erros, `/generation`, `/key`).
  - `LLMGateway`: reserva → envio → liquidação; retentativa só quando não houve cobrança; chamadas incertas nunca repetidas; bloqueio de troca de modelo; um reparo de JSON inválido.
  - Registro de prompts: 4 políticas e 12 papéis anotados por requisito, versões imutáveis, editar/duplicar/restaurar/comparar, variantes `specialized` e `full`, verificação de cobertura.
  - Orquestrador persistente: dependências, leases com heartbeat, pausa/retomada/cancelamento, reprocessamento sem apagar histórico, pausa por orçamento, gate de conclusão.
  - Grafo de criação integral (16 etapas) com handlers da Fase 1 e revisão humana bloqueando a exportação.
  - API local (só 127.0.0.1, Host/Origin verificados), CLI (`serve`, `migrate`, `check`, `backup`), interface React com Painel, Monitor, Prompts e Orçamento, inicializadores `cardfactory.cmd`/`.sh`, CI com Windows e Linux só com simulações.
- **Efetivamente testado**: 98 testes pytest sem rede (incluindo SIGKILL real no meio da execução, 25 reservas concorrentes, vazamento de chave em respostas/logs/arquivos, provedor pago sem autorização) e smoke Playwright das quatro telas.
- **Limitações**:
  - Os handlers das etapas ainda não produzem conteúdo médico: cards gerados pelo simulado têm origem `MOCK` e as saídas trazem `phase: 1`.
  - A exportação gera só um manifesto preliminar em JSON; TSV para o Anki chega na Fase 3.
  - O adaptador OpenRouter nunca foi chamado de verdade (sem autorização de gasto).
  - O inicializador do Windows não foi executado em uma máquina Windows real; a CI roda os testes em `windows-latest`.
- **Custos**: R$ 0,00.
- **Próxima etapa**: Fase 2 — pesquisa e conhecimento.


## Fase 0 — concluída (24/11/2026)

- **Implementado**: nenhum código. Documentos de especificação e arquitetura (ver IMPLEMENTATION_PLAN §Fase 0).
- **Efetivamente testado**: a matriz é gerada por script (`requirements/build_matrix.py`), que verifica IDs duplicados; hashes SHA-256 dos documentos normativos calculados; contraste da paleta medido (WCAG) em fundos #101114, #000000 e #FFFFFF.
- **Resultados**: 221 requisitos (115 DET, 63 HIB, 37 IA, 4 PESQ, 2 HUM; 108 P0); 146 falhas históricas mapeadas; paleta passa ≥7,3:1 no escuro e falha (1,2–2,6:1) no claro.
- **Limitações**: documentação do OpenRouter lida em 24/11/2026, com algumas páginas não confirmadas (listadas em OPENROUTER.md); comportamento de GUID vazio no Anki não testado.
- **Pendências do proprietário**: conjunto de 30–60 cards de referência para o benchmark. AMB-01, 02 e 06 adotadas conforme proposta (o proprietário delegou as decisões técnicas).
- **Decisões tomadas**: ADR-0001 a 0012 (ARCHITECTURE §10).
- **Próxima etapa**: Fase 1 — Fundação.
- **Custos**: R$ 0,00 (nenhuma chamada paga).
- **Documentação completa da seção 31** gravada no primeiro commit (README, AGENTS, PIPELINE, PROMPT_REGISTRY, QUALITY_POLICY, SECURITY, ADRs, especificação verbatim).
