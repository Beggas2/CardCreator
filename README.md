# CardFactory

Sistema local de produção e auditoria de flashcards médicos com rastreabilidade científica, controle financeiro e revisão humana. Os documentos normativos do produto (Criador V2.0 e Revisor V2.0) estão preservados sem alteração em `docs/normative/`.

> Estado atual: veja `STATUS.md`. Aprovação automática por IA **não** é certificação médica.

## Requisitos

- Windows 10/11, macOS ou Linux
- [uv](https://docs.astral.sh/uv/) (gerencia Python 3.12+ e dependências)
- Node.js 20+ apenas para desenvolver a interface

## Instalação e inicialização (Windows)

```powershell
git clone https://github.com/Beggas2/CardCreator.git
cd CardCreator
copy .env.example .env      # opcional: sem chave, só o provedor simulado funciona
.\cardfactory.cmd           # cria o ambiente, aplica migrações e abre http://127.0.0.1:8765
```

Em macOS/Linux: `./cardfactory.sh`.

## Configuração

| Variável | Padrão | Função |
|---|---|---|
| `OPENROUTER_API_KEY` | vazio | Chave do provedor real. Sem ela, apenas o provedor simulado |
| `CARDFACTORY_DATA_DIR` | `./data` | Banco SQLite, documentos e exportações |
| `CARDFACTORY_PORT` | `8765` | Porta local (bind sempre em 127.0.0.1) |

Mesmo com chave, **nenhuma chamada paga acontece sem uma autorização de gasto registrada na tela de Orçamento**.

## Testes

```bash
cd backend
uv run pytest            # unitários + integração; nunca acessam a rede nem gastam créditos
uv run ruff check .
uv run cardfactory check # hashes dos documentos normativos + cobertura de requisitos nos prompts
cd ../frontend
npm ci && npm run build  # a interface compilada (frontend/dist) fica no repositório
npm run smoke            # Playwright: sobe o app com o simulado e percorre as telas
```

A interface compilada é versionada para que o uso no Windows exija apenas o `uv`; Node.js só é necessário para alterar a interface.

## Recuperação de falhas

- O banco usa SQLite em modo WAL. Ao reiniciar, tarefas interrompidas são retomadas; chamadas cujo resultado é incerto ficam em `UNCERTAIN` e são reconciliadas antes de qualquer repetição.
- Backup: `uv run --project backend cardfactory backup` grava uma cópia consistente em `data/backups/` (funciona com o app aberto).

## Documentação

`ARCHITECTURE.md` · `REQUIREMENTS.md` · `REQUIREMENTS_TRACEABILITY.md` · `DATA_MODEL.md` · `CONTRACTS.md` · `PIPELINE.md` · `PROMPT_REGISTRY.md` · `QUALITY_POLICY.md` · `BENCHMARK_PROTOCOL.md` · `COST_CONTROL.md` · `SECURITY.md` · `IMPLEMENTATION_PLAN.md` · `STATUS.md` · `AGENTS.md` · `docs/adr/` · `docs/providers/OPENROUTER.md`
