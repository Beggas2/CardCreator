# COST_CONTROL — Controle financeiro

Obrigatório antes de qualquer produção real (E§20). Nenhuma chamada paga sem `spend_authorization` ativa concedida pelo proprietário (FIN-012).

## 1. Unidades

- Moeda original: USD (créditos OpenRouter). Valores em `Decimal`, 8 casas.
- Conversão para BRL por `fx_rate` datada e informada pelo proprietário (ou cotação manual registrada), acrescida de **margem de câmbio/IOF/taxas configurável** (padrão 10%). O orçamento é sempre comparado em BRL **com margem**: `brl = usd × taxa × (1 + margem)`.

## 2. Hierarquia de orçamentos

`PROJECT ⊃ EXPERIMENT ⊃ RUN ⊃ STAGE ⊃ BATCH`, mais limite por `MODEL`. Uma chamada é cobrada contra **todos** os orçamentos aplicáveis; basta um sem saldo para bloquear.

Semente para o experimento de R$100 (configurável, não obrigatória de consumo):

| Etapa | R$ |
|---|---|
| Pesquisa e planejamento | 10 |
| Benchmark | 15 |
| Geração | 20 |
| Auditoria científica | 25 |
| Auditoria pedagógica | 10 |
| Classificação e deduplicação | 5 |
| Reserva e correções | 15 |

Realocação entre etapas: o sistema **propõe**, o proprietário aprova (registro em `budget_ledger` tipo `ADJUST` com autor).

## 3. Estimativa antes da chamada

```
max_usd = pricing.request
        + tokens_in_exatos × pricing.prompt                 (contagem por tokenizer ou limite superior: caracteres/2,5)
        + max_output_tokens × max(pricing.completion, pricing.internal_reasoning)
        + n_pesquisas_max × preço_pesquisa_do_motor
        + páginas_OCR × preço_OCR
        + reparo_JSON_permitido (1 chamada adicional estimada do mesmo modo)
```

Cache **não** reduz a estimativa máxima (só o custo real). Se algum termo não puder ser estimado (preço ausente no catálogo, motor de pesquisa sem preço, modelo com cobrança variável desconhecida), `safe=false` e a chamada é **bloqueada** ou exige confirmação explícita do proprietário.

## 4. Reserva atômica

```
BEGIN IMMEDIATE;
  para cada orçamento aplicável:
     confirmado + reservado_ativo + max_brl(nova) <= limite   senão ROLLBACK → BudgetExceeded
  INSERT budget_ledger(RESERVE, max) para cada orçamento
  INSERT llm_call(state=RESERVED)
COMMIT;
```

SQLite serializa escritores com `BEGIN IMMEDIATE`, então duas tarefas concorrentes não reservam o mesmo saldo. Testado com N threads disputando o último real (`test_budget_reservation_atomic`).

## 5. Ciclo da chamada

`RESERVED → SENT → (SUCCEEDED | FAILED_BILLED | FAILED_UNBILLED | UNCERTAIN) → RECONCILED`

- **SUCCEEDED**: `confirm(custo real de usage.cost)`; libera a diferença da reserva.
- **FAILED_UNBILLED**: só quando há evidência (erro antes da geração: 400/401/402/403 pré-geração); libera a reserva.
- **FAILED_BILLED** / **UNCERTAIN** (timeout, conexão caída após envio, stream interrompido): a reserva **permanece**; job de reconciliação consulta `GET /generation?id=` (quando houver id) ou o `usage` da chave; sem confirmação, o valor máximo permanece contabilizado e a tarefa não é repetida automaticamente (PRV-007).
- Chamadas canceladas pelo usuário seguem o mesmo caminho (abortar não garante ausência de cobrança).

## 6. Limites operacionais (por produção e etapa)

`max_tokens_saida`, `max_pesquisas`, `max_resultados_por_pesquisa`, `max_ferramentas`, `max_correcoes_por_defeito` (padrão 2), `concorrencia` (padrão 2), `max_paginas_ocr`, `max_preco_por_milhao` (repassado como `provider.max_price`).

## 7. Parada

Ao atingir 100% de qualquer orçamento: estado `PAUSED_BUDGET`, nenhuma nova reserva, chamadas em voo concluem e reconciliam, estado preservado para retomada. Alertas em 50%, 75%, 90%.

## 8. Proibições

O código não contém: compra de créditos, alteração de limites da chave, troca automática para modelo mais caro, fallback silencioso para outro modelo. Troca de modelo é ação humana registrada.

## 9. Camada externa (recomendação ao proprietário)

Criar no OpenRouter uma chave **exclusiva** do CardFactory com `limit` igual ao orçamento autorizado em USD (ex.: US$ 15 para R$100 com folga) e sem recarga automática. O app lê `GET /api/v1/key` antes de cada execução e se recusa a iniciar se `limit_remaining` for menor que o orçamento local restante convertido (inconsistência → alerta). O limite do provedor é proteção extra, não o controle principal.

## 10. Métricas

Custo por objetivo, por card gerado, auditado, aprovado por IA e aprovado humanamente; custo de falhas cobradas; custo por etapa e por modelo; tudo com denominador explícito (FIN-009).
