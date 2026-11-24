# REQUIREMENTS — Síntese, hierarquia e ambiguidades

Documentos normativos (preservados byte a byte em `docs/normative/`):

| Arquivo | SHA-256 | Observação |
|---|---|---|
| `Prompt Criação.txt` (Criador V2.0, 46 seções, 3.824 linhas) | `e6cedf5789d9639a36fcc27ac4664974e47536099e42f2c176b17dff829d8112` | UTF-8, quebras CRLF |
| `Prompt Revisor.txt` (Revisor V2.0, 61 seções, 4.286 linhas) | `d009c4ca63b9ffcfe5f662bfb79819bbd9afa3491b9ac2444964cba77c4abaf9` | UTF-8, quebras CRLF |

Como os arquivos usam CRLF, o repositório terá `.gitattributes` com `docs/normative/* -text` para impedir normalização de fim de linha, e um teste (`test_normative_docs_hash`) que falha se o hash mudar.

A matriz completa está em `REQUIREMENTS_TRACEABILITY.md` (221 requisitos) e `REGRESSION_MAP.md` (64 + 82 falhas históricas). Este documento registra o que a matriz não mostra: como os dois documentos se relacionam, a hierarquia unificada e as inconsistências encontradas.

## 1. Papéis dos documentos

O Criador define **como construir** conhecimento e transformá-lo em cards. O Revisor define **como verificar independentemente** o resultado e proteger a coleção. Compartilham ciência, pedagogia, padrão visual e formato técnico; divergem em pontos de detalhe listados abaixo. No CardFactory eles alimentam papéis diferentes do Prompt Registry (pesquisador, planejador, criador × auditores, resolvedor), e o código implementa tudo o que é determinístico (validadores, serialização, paleta, cálculo, estados, gates).

## 2. Classificação dos requisitos (resumo)

| Classe | Qtde | Exemplos |
|---|---|---|
| DET — código | 115 | serialização TSV, paleta, allowlist HTML, GUID, reserva de orçamento, máquina de estados, cálculo de diluição |
| HIB — híbrido | 63 | varredura de termos vagos (código acha, IA julga), deduplicação (código gera candidatos, IA classifica) |
| IA — modelo | 37 | granularidade, recuperação ativa, mapa ideal, pontos de decisão |
| PESQ — pesquisa externa | 4 (+ partes de vários HIB) | conferência do documento original, vigência, disponibilidade BR |
| HUM — humano | 2 (+ etapa obrigatória do lote experimental) | aprovação humana, limite na chave do provedor |

Princípio derivado: **o modelo nunca é a fonte de um fato de controle**. Contagens, estados, "validado", "testado", "importado", custos e citações vêm de registros do banco produzidos por código.

## 3. Hierarquia unificada (ADR-0003)

O Criador tem 12 níveis (segurança e correção juntas; sem integridade da coleção). O Revisor tem 14 (separa segurança de correção e inclui "integridade da coleção" em 4º). A especificação cita "segurança, correção científica, vigência, qualidade de aprendizagem, integridade e estética". Adotamos a lista do Revisor por ser superconjunto compatível:

1. Segurança clínica · 2. Correção científica · 3. Vigência e aplicabilidade · 4. Integridade da coleção e preservação do conhecimento válido · 5. Clareza do objetivo · 6. Recuperação ativa · 7. Completude no escopo · 8. Precisão da autoavaliação · 9. Compreensão e transferência · 10. Retenção · 11. Eficiência de revisão · 12. Legibilidade e acessibilidade · 13. Consistência visual · 14. Estética.

Ponto de atenção: na especificação, "qualidade de aprendizagem" aparece **antes** de "integridade"; no Revisor, integridade vem antes da clareza do objetivo. Na prática o conflito só aparece quando preservar um GUID/histórico prejudicaria a aprendizagem. Os dois documentos já resolvem esse caso (R§2: "nunca preserve informação incorreta para manter histórico"; C§29.2 / R§38.2: mudança substancial de objetivo não preserva histórico automaticamente). Por isso mantemos a ordem do Revisor sem alterar comportamento. Decisão adotada em 24/11/2026 (AMB-02).

## 4. Ambiguidades e inconsistências encontradas

| ID | Tema | Onde | Problema | Decisão proposta | Precisa do proprietário? |
|---|---|---|---|---|---|
| AMB-01 | **Modo claro no Anki** | C§17.8, R§30.14, C§30.3, E§12 | Os componentes usam cores inline da paleta escura e os documentos mandam "não fixar o fundo". No Anki em modo claro, o texto fica ilegível: medi contraste em fundo branco de 1,24:1 (#E5E7EB), 1,44:1 (#FCD34D), 1,67:1 (#7DD3FC), 1,90:1 (#FCA5A5), 2,56:1 (#94A3B8). Em fundo escuro todos passam (7,4 a 15,3:1). Resolver exigiria CSS no tipo de nota (classe `.nightMode`/`.night_mode`), o que esbarra em "não criar/alterar tipo de nota" (C§30.1). | Exportar o padrão V2.0 como está (escuro) e tratar o modo claro só no preview. Registrar como limitação. Opção futura: tipo de nota com CSS de tema, mediante autorização. | Decidido em 24/11/2026: proposta adotada (proprietário delegou). Reabrir se o modo claro virar requisito comercial. |
| AMB-02 | Ordem integridade × aprendizagem | C§2, R§2, E§2 | Ver §3. | Ordem do Revisor. | Decidido em 24/11/2026: proposta adotada. |
| AMB-03 | Dimensões do mapa ideal | C§9 (56), R§13 (56) | Listas quase iguais: C tem "padrão-ouro" e "diferenças entre diretrizes"; R tem "integração clínica" e "divergências". | União deduplicada com 57 dimensões, cada uma com referência às duas origens. | Não |
| AMB-04 | Estados de cobertura | C§9 (5 estados por dimensão), R§14.1 (9 por objetivo), C§27.6 (7 por questão), R§24.7 (9 por questão) | Vocabulários diferentes para coisas parecidas. | Três enums distintos (dimensão, objetivo, questão) usando os termos do Revisor, com tabela de equivalência para os termos do Criador. | Não |
| AMB-05 | Operações | C§32.4 (UPDATE genérico), R§37 (UPDATE_CONTENT/FRONT/PEDAGOGY/STYLE, QUARANTINE, REVIEW_REQUIRED) | O Criador usa um UPDATE único. | Enum do Revisor; o UPDATE do Criador é mapeado para o subtipo mais específico. | Não |
| AMB-06 | Peso do negrito nos componentes | C§30.3, C§18.2 | "Negrito = alvo de recuperação", mas os componentes de referência aplicam `font-weight:600` a todo valor âmbar e alerta vermelho, mesmo quando não são alvo. | Peso derivado de `retrieval_target`: alvo → 700; valor/alerta não alvo → cor sem negrito (ADR-0006). Os componentes de referência continuam válidos para alvos. | Decidido em 24/11/2026: proposta adotada; validar visualmente na Fase 3. |
| AMB-07 | Prefixo `IGOR::` | C§6.3, C§38.4 | O validador exige `deck.startswith("IGOR::")`; o produto comercial ainda não tem nome. | Prefixo configurável por coleção, padrão `IGOR::`. | Não |
| AMB-08 | GUID vazio para notas novas com `#guid column:1` | C§31.3, R§38.7 | Os documentos dizem "quando a importação permitir". Não verificado em qual versão do Anki um GUID vazio gera nota nova. | Testar em coleção descartável com o pacote `anki` (pylib) na Fase 3; até lá, fallback para GUID gerado pelo CardFactory com o algoritmo do Anki, registrado no manifesto. | Não (técnico) |
| AMB-09 | Perfil do estudante | C§1 (AMP, AMRIGS), R§1 (+ USP-RP, IAMSPE, EsFCEx, emergência/UTI) | Perfis diferentes; e o produto é comercial, então o "estudante" passa a ser o público do IgorSRS. | Perfil pedagógico versionado e configurável; padrão = união dos dois. | Sim, quando houver definição comercial. |
| AMB-10 | Marcador `IMAGEM:` | R§32.1 | Fluxo pessoal usa identificador no card; produção comercial deve usar manifesto. | Manifesto de mídia; nenhum marcador no card comercial. | Não |
| AMB-11 | Momento da análise de provas | C§5 (passo 16, após 1ª versão), E§10 (passo 12, antes de definir quantidade), R§13 (mapa antes das questões) | Ordem diferente. | Provas de **planejamento** entram na priorização (E§10) depois do mapa independente; provas de **avaliação** ficam reservadas e só entram na auditoria de cobertura (E§18, separação de conjuntos). | Não |
| AMB-12 | Meta R$100 / 1.000 cards | E§1, E§28 | Equivale a ~R$0,10 por card aprovado incluindo pesquisa e duas auditorias com modelos de famílias diferentes. Pode ser inviável com modelos de ponta. | Tratar como hipótese a testar no microbenchmark; o sistema reporta custo por card aprovado real e propõe ajuste de quantidade, nunca de qualidade. | Ciente; decisão após benchmark. |
| AMB-13 | "Cores estruturais" #000000 | C§17.1 (texto, sem hex), C§38.4 e R§30.1 (#000000) | Pequena diferença de redação. | Aceitar #000000 como estrutural. | Não |
| AMB-14 | Lotes de 20 vs 20–25 | E§11, R§58 | Compatíveis. | Padrão 20, ajustável. | Não |
| AMB-15 | Formato sem GUID | R§43.3 | Só o Revisor define; a especificação menciona apenas principal e simplificado. | Implementar os três formatos. | Não |
| AMB-16 | Batch × pesquisa web | E§4, docs OpenRouter | O Batch da OpenRouter existe (50% do preço), mas não aceita pesquisa web, ordem de provedores nem ZDR. | Batch só para etapas sem pesquisa (ex.: auditoria pedagógica, classificação), após benchmark mostrar equivalência. | Não |

## 5. Requisitos comerciais identificados

- Conteúdo textual original; materiais de terceiros (Osler, apostilas, bancos de questões) só para comparação e lacunas (E§5, R§23.4, R§56).
- Direitos de mídia verificados; dados pessoais removidos (C§25.1, R§56).
- Rastreabilidade, identidade estável, versionamento, processo de atualização (R§56, E§23, E§25).
- Aprovação por IA ≠ certificação médica; revisão humana qualificada para alto risco (R§56, E§27).
- Integração futura com IgorSRS apenas por contrato versionado, sem modificar o app (E§3, E§24).

## 6. Hierarquia de aprovação (resumo de E§27 + R§49 + R§55)

Liberação é um **gate não compensatório**: qualquer bloqueio (defeito crítico, afirmação crítica não verificada, referência inventada, contradição não resolvida, erro de identidade, erro técnico bloqueante, problema de direitos, revisão humana pendente) impede, independentemente de qualquer outra nota.
