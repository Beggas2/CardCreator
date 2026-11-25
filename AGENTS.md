# AGENTS.md — Instruções para agentes de desenvolvimento

Leia antes de alterar qualquer coisa:

1. `docs/spec/CARDFACTORY_ESPECIFICACAO.md` (especificação do proprietário, referências `E§n`).
2. `docs/normative/` — **somente leitura**. Nunca editar, reformatar ou normalizar fins de linha. `test_normative_docs_hash` falha se os bytes mudarem.
3. `REQUIREMENTS.md`, `REQUIREMENTS_TRACEABILITY.md`, `ARCHITECTURE.md`, `STATUS.md`.

## Regras invioláveis

- **Nenhuma chamada paga** sem `spend_authorization` registrada pelo proprietário. Testes usam `MockProvider` e nunca acessam a rede.
- Nunca modificar o IgorSRS.
- Nunca codificar IDs de modelos: use o catálogo sincronizado.
- Nada destrutivo: não há exclusão de notas; exclusões são manifestos.
- Fatos de controle (estados, contagens, custos, "validado", "testado", "importado") vêm do banco, nunca de texto do modelo.
- O renderizador é função pura; o modelo nunca envia HTML, cor ou CSS.
- Não implementar funcionalidade fictícia. O que não existe retorna `NOT_IMPLEMENTED`.
- Segredos só via env/keyring; nada de chaves em logs, exportações ou commits.

## Fluxo de trabalho

- Ao implementar um requisito, cite o ID (ex.: `FIN-002`) no commit e no teste; atualize o status no script `requirements/build_matrix.py` e regenere (`python requirements/build_matrix.py`).
- Toda falha nova relevante vira caso em `regression_case` e em `REGRESSION_MAP.md`.
- Ao fim de cada fase, atualize `STATUS.md` com: implementado, efetivamente testado, resultados, limitações, pendências, decisões, próxima etapa e custos.
- Decisão arquitetural nova → novo arquivo em `docs/adr/`.

## Comandos

```bash
cd backend && uv sync && uv run pytest && uv run ruff check . && uv run alembic upgrade head
cd frontend && npm ci && npm run dev
```
