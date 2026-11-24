# STATUS

## Fase 6 — experimento com modelos reais (em andamento)

- 24/11/2026: a proprietária autorizou a Etapa 1 até R$ 15.
- Pronto: `cardfactory experimento` sincroniza o catálogo da OpenRouter (consulta gratuita), escolhe um candidato
  por família por regra (saída estruturada, contexto ≥ 64 mil tokens, lançado nos últimos 540 dias, teto de
  preço) e estima o custo das rodadas em reais. Grava `data/experimento/etapa1-plano.md`. Também em
  `GET /api/experiment/plan`. Nenhuma chamada de geração é feita.
- Falta: a proprietária aprovar a lista; depois executar as rodadas A e B com o orçamento de R$ 15 cadastrado.
- O ambiente de desenvolvimento em nuvem não alcança a OpenRouter; o catálogo e as rodadas rodam na máquina dela.

## Fase 5 — concluída (24/11/2026)

- **Implementado**:
  - Mesa de revisão (tela Revisão): fila priorizada (bloqueios e pendências primeiro) com filtros por projeto, estado e deck; prévia, bloqueios, defeitos, afirmações e propostas no mesmo lugar; atalhos de teclado (j/k, a, u).
  - Aprovação humana distinta da automática: só é aceita sem bloqueio aberto e com o nome de quem revisou. Rejeitar e pedir alteração exigem motivo tipificado (13 motivos ligados às categorias de defeito). Pedir alteração cria defeito de origem HUMAN, que a correção trata.
  - Decisões append-only com desfazer (nova decisão UNDO que restaura o estado e anula os defeitos que ela criou). Tempo de revisão e "aprovado com edição" registrados.
  - Propostas da IA (exclusão, fusão, mover, dividir...) só valem com decisão humana. Exclusão aceita vira REJECTED: a nota nunca é apagada.
  - Aprendizado editorial: frequência de motivos por layout, taxa de aprovação, tempo mediano; lições escritas por humanos, aceitas e incorporadas à política editorial como versão nova do prompt (reversível).
  - Princípios dos 40 cards de referência analisados (`benchmarks/reference/PRINCIPIOS.md`) e convertidos na política `editorial` (regras gerais, sem copiar exemplos), incluída no criador, no corretor e no auditor pedagógico.
  - Laboratório: conjuntos KNOWN_DEFECTS (11 defeitos plantados com gabarito + 12 cards limpos) e REFERENCE (40 cards, escabiose = dev, Kawasaki = eval), split eval selado com registro de cada consulta, execuções por varredura determinística ou auditor de IA, métricas de detecção e falso alarme com intervalo exato de Clopper-Pearson, prompt hash, modelo e custo gravados.
  - Comparação cega: rótulos e ordem aleatórios, origem (card, versão, autor e modelo) revelada só depois da escolha e da justificativa gravadas.
  - Nova varredura determinística: a frente contém o alvo de recuperação (PED-001).
- **Efetivamente testado**: 239 testes pytest sem rede (mais 1 opcional) e smoke Playwright passando pelas telas Revisão (pedir alteração e desfazer, 412 px sem rolagem horizontal) e Laboratório (benchmark e comparação cega).
- **Resultado do benchmark sem custo** (varreduras determinísticas, split dev): detecção 4/6 (IC95% 22–96%), falso alarme 0/6 (IC95% 0–46%). As amostras são pequenas; o intervalo largo é real. Os auditores de IA só rodaram com o simulado, que não detecta nada: o número real depende de autorização de gasto.
- **Limitações**:
  - O split eval de KNOWN_DEFECTS tem 11 itens; serve para triagem, não para afirmar taxa de erro baixa.
  - O conjunto de referência não tem gabarito: o que os auditores apontarem nele precisa de revisão humana.
  - Propostas MOVE/SPLIT aceitas não são aplicadas automaticamente; a edição é manual.
- **Custos**: R$ 0,00.
- **Próxima etapa**: Fase 6 (experimento com modelos reais), **somente com autorização de gasto**. Etapa 1 prevista: microbenchmark de até R$ 15 (BENCHMARK_PROTOCOL §5).

## Fase 4 — concluída (24/11/2026)

- **Implementado**:
  - Contratos estritos dos auditores: científico (veredito por afirmação com trechos), pedagógico (17 dimensões, KEEP como padrão), segurança (riscos, injeção, terceiros, dados pessoais), cobertura (mapa independente de 57 dimensões, objetivos, lacunas, 28 perguntas de autossuficiência), contradição e correção (papel `corrector` novo).
  - Defeitos com 19 categorias e 5 gravidades; varreduras determinísticas (frente dependente de contexto, sigla ambígua, redundância interna, soma de escore, aritmética de dose por peso, número diferente da afirmação verificada).
  - Isolamento do auditor (AUD-001): o card vai sem `validation_status` nem `limitations` do criador, sem auditorias anteriores; o contexto entregue fica registrado em `audit.context_manifest`.
  - Correção limitada: no máximo 2 tentativas automáticas por defeito, depois ESCALATED ao humano; card legado é convertido para card.v2 no mesmo card (GUID preservado); mudança substancial de objetivo gera proposta REVIEW_REQUIRED (INT-003).
  - Reauditoria só das versões novas: o defeito que não reaparece vira FIXED; afirmação que era CONFIRMADA e piorou vira defeito REGRESSION.
  - Deduplicação em camadas (texto normalizado, léxica, numérica, objetivo) classificada por IA; contradição vira defeito HIGH nos dois cards; exclusão e fusão são só propostas (DED-003).
  - Veredito por dimensão (científica, pedagógica, cobertura, técnica) do ORIGINAL e do CORRIGIDO, nunca média; a científica fica "não verificada" quando nenhum card tem afirmação com veredito.
  - Portão de liberação não compensatório no exportador: quarentena, defeito crítico/alto aberto, afirmação crítica sem CONFIRMADA, erro técnico ou contradição aberta bloqueiam, mesmo com aprovação humana. Defeito crítico não pode ser justificado. Na prévia o card sai e o bloqueio vai para o manifesto.
  - Modo FULL_AUDIT para decks existentes: inventário vincula os cards (por lote de importação, ids ou deck), pesquisa e extração montam o acervo, e cada card sem afirmações recebe os trechos mais próximos do acervo. Quarentena da importação nunca é retirada pela auditoria.
  - Relatório de auditoria (estados, defeitos, vereditos, operações, magnitude com alerta >30% só para deck existente, reconciliação do estado final) e tela Auditoria.
  - Cards de referência da proprietária (40) guardados em `benchmarks/reference/` byte a byte.
- **Efetivamente testado**: 227 testes pytest sem rede (mais 1 opcional) e smoke Playwright incluindo a tela Auditoria em 412 px. A criação integral simulada percorre auditoria → correção → reauditoria (defeito de teste corrigido e marcado FIXED). Os 40 cards de referência foram importados e varridos: 1 achado determinístico (sigla PCR sem definição no card de Kawasaki incompleto, gravidade baixa).
- **Limitações**:
  - Todas as auditorias de IA rodaram só com o simulado. A auditoria real dos 40 cards de referência precisa de autorização de gasto.
  - Os 40 cards de referência entram com GUID vazio, então a importação os coloca em quarentena (regra de preservação de GUID); isso não afeta a auditoria nem o benchmark.
  - Seleção do acervo para decks importados é lexical (sem embeddings).
  - Propostas (fusão, exclusão, mover, dividir) ficam registradas; a decisão humana sobre elas é da mesa de revisão (Fase 5).
- **Custos**: R$ 0,00.
- **Próxima etapa**: Fase 5, mesa de revisão humana, benchmark com os cards de referência e comparador cego.

## Fase 3 — concluída (24/11/2026)

- **Implementado**:
  - Contrato card.v2 (12 layouts, 12 tipos cognitivos A–L, três camadas) e generation_batch.v1 em JSON Schema estrito, com regras determinísticas (essencial obrigatório, sem alvo no complemento, regra de combinação em critérios, HTML do modelo recusado).
  - Renderizador puro card → HTML: cor por semântica, negrito só em alvo de recuperação (AMB-06), tokens de tipografia e espaçamento, alinhamento por layout, tabelas responsivas, nunca fixa fundo nem cria rótulos automáticos.
  - Paleta clara equivalente só na prévia (AMB-01), com contraste ≥ 4,5:1 conferido em teste.
  - Validador de HTML (C§38.4 ampliado: allowlist, eventos, CSS proibido, paleta, mídia externa) e alertas pedagógicos (C§38.2) com ciclo aberto/corrigido/justificado; erros bloqueiam e não podem ser justificados.
  - Versões append-only, rollback como nova versão, diff, HTML derivado registrado, operações (R§37) e mídia só com licença e direitos verificados.
  - Exportação versionada nos três formatos (principal com GUID, sem GUID, simplificado), releitura campo a campo, validador de arquivo, diff com a exportação anterior, manifesto, pendências e mídia. Prévias sem revisão saem rotuladas PREVIA_NAO_REVISADA.
  - Etapa GENERATION real: reserva de objetivos, só cita afirmações/trechos/fontes recebidos, lote reduzido ao meio em truncamento, retomada sem duplicar cards.
  - Telas Cards (prévia escuro/claro, celular/desktop, aprovação mínima, edição, versões, justificativas), Galeria visual e Exportação.
- **Efetivamente testado**: 217 testes pytest sem rede (mais 1 opcional) (inclui regressões técnicas C§40 itens 1–9) e smoke Playwright de todas as telas, com verificação de rolagem horizontal em 412 px. Importação real numa coleção Anki descartável (pacote `anki` 26.09.4) passou; esse teste é opcional e fica pulado quando o pacote não está instalado.
- **Decisão resolvida**: AMB-08. GUID vazio cria nota nova no Anki; exportamos GUID vazio e a tag `cf::<card_key>` para reconciliar.
- **Limitações**:
  - Cards reais dependem do modelo; até agora só o simulado gerou cards (conteúdo [SIMULADO]).
  - A aprovação na tela Cards é mínima; a mesa de revisão com motivos tipificados é da Fase 5.
  - Cards legados importados ainda não tinham conversor para card.v2 (feito na Fase 4).
  - Auditorias científica, pedagógica e de cobertura eram simplificadas (feitas na Fase 4).
- **Custos**: R$ 0,00.
- **Próxima etapa**: Fase 4, auditoria (científica, pedagógica, cobertura, segurança), correção e deduplicação.

## Fase 2 — concluída (24/11/2026)

- **Implementado**:
  - Biblioteca científica: fontes, versões (publicação, atualização de página e vigência separadas), documentos com 7 estados e histórico de transições, seções, busca FTS5 sem acento com filtros.
  - Leitura local de HTML (títulos, tabelas, rodapés), texto e PDF; páginas sem texto e tabelas irregulares viram pendência.
  - Evidência só é aceita com trecho literal da seção.
  - Download com proteção SSRF.
  - Importação de export do Anki com relatório por linha, quarentena e GUID preservado; reimportação versionada.
  - Importação de questões com separação determinística planejamento/avaliação.
  - Conhecimento: 57 dimensões (união C§9 + R§13), comparação com mapa independente, objetivos com reserva atômica, cobertura com denominador explícito, afirmações por componente, veredictos append-only.
  - Papéis pesquisador, extrator e planejador ligados ao pipeline com contratos em JSON Schema estrito; violação de contrato não repete a chamada.
  - Telas Biblioteca, Conhecimento e Importação.
- **Efetivamente testado**: 148 testes pytest sem rede e smoke Playwright das sete telas; CI verde em Ubuntu e Windows.
- **Limitações**:
  - Papéis de IA testados só com o simulado. A qualidade real de extração e planejamento depende do modelo e será medida no benchmark (Fase 5).
  - Sem OCR (páginas escaneadas ficam pendentes).
  - Sem busca semântica; só textual. Embeddings entram com a deduplicação (Fase 4).
  - Mapa independente e auditoria de cobertura ficam para a Fase 4.
- **Custos**: R$ 0,00.
- **Próxima etapa**: Fase 3, geração e renderização (card.v2, renderizador, validadores, exportação TSV).


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
