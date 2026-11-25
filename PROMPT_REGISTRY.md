# PROMPT_REGISTRY — Sistema de prompts

## Estrutura

```
prompts/
  policies/   scientific.md  pedagogical.md  visual.md  integrity.md
  roles/      researcher.md  extractor.md  planner.md  creator.md
              auditor_scientific.md  auditor_pedagogical.md  auditor_coverage.md
              auditor_security.md  resolver.md  classifier.md  contradiction.md  comparator.md
  manifest.yaml   # papel → políticas incluídas, contrato de saída, req_ids obrigatórios
```

Cada bloco de regra é anotado com os requisitos e seções de origem:

```markdown
<!-- req: SCI-013 | C§7.6 R§10.3 -->
Uma fonte que confirma a indicação não confirma automaticamente dose, via, duração ou população.
```

## Regras

1. Os arquivos em `docs/normative/` são a fonte; os prompts operacionais são derivados e **nunca** os substituem.
2. Na importação para o banco, cada arquivo vira `prompt_version` imutável com hash SHA-256 do texto final composto.
3. **Cobertura**: `manifest.yaml` lista os `req_ids` obrigatórios por papel; `test_prompt_rule_coverage` falha se algum não aparecer anotado no prompt composto daquele papel.
4. Toda chamada registra `prompt_version_ids` e `prompt_hash`. Editar um prompt cria nova versão; chamadas antigas continuam apontando para a versão usada.
5. O sistema não altera prompts normativos nem políticas automaticamente (MNT-004). Aprendizado editorial entra como **exemplos recuperados**, não como mudança de política.
6. Conteúdo externo (páginas, PDFs, cards importados) é inserido entre delimitadores `<untrusted_document id=…>` com a instrução de que é dado, não instrução (SEC-002).
7. Variantes para benchmark: `full` (documento integral), `specialized`, `specialized+examples`, `specialized+retrieved` (PRM-004).

## Interface

Editor de prompts: visualizar, editar (gera nova versão), duplicar, comparar (diff), restaurar (nova versão com conteúdo antigo) e ver requisitos associados.
