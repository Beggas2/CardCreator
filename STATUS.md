# STATUS

## Fase 0 — concluída (24/11/2026)

- **Implementado**: nenhum código. Documentos de especificação e arquitetura (ver IMPLEMENTATION_PLAN §Fase 0).
- **Efetivamente testado**: a matriz é gerada por script (`requirements/build_matrix.py`), que verifica IDs duplicados; hashes SHA-256 dos documentos normativos calculados; contraste da paleta medido (WCAG) em fundos #101114, #000000 e #FFFFFF.
- **Resultados**: 221 requisitos (115 DET, 63 HIB, 37 IA, 4 PESQ, 2 HUM; 108 P0); 146 falhas históricas mapeadas; paleta passa ≥7,3:1 no escuro e falha (1,2–2,6:1) no claro.
- **Limitações**: documentação do OpenRouter lida em 24/11/2026, com algumas páginas não confirmadas (listadas em OPENROUTER.md); comportamento de GUID vazio no Anki não testado.
- **Pendências do proprietário**: conjunto de 30–60 cards de referência para o benchmark. AMB-01, 02 e 06 adotadas conforme proposta (o proprietário delegou as decisões técnicas).
- **Decisões tomadas**: ADR-0001 a 0012 (ARCHITECTURE §10).
- **Próxima etapa**: Fase 1 — Fundação (em andamento).
- **Custos**: R$ 0,00 (nenhuma chamada paga).
- **Documentação completa da seção 31** gravada no primeiro commit (README, AGENTS, PIPELINE, PROMPT_REGISTRY, QUALITY_POLICY, SECURITY, ADRs, especificação verbatim).
