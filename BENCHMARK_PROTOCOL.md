# BENCHMARK_PROTOCOL — Avaliação de modelos, prompts e pipelines

Objetivo: escolher modelos e prompts por evidência, sem presumir qual IA é superior (E§19), e estimar com honestidade a qualidade e o custo por card **aprovado**.

## 1. Conjuntos

| Conjunto | Conteúdo | Uso |
|---|---|---|
| **Referência** | Cards excelentes fornecidos pelo proprietário (meta inicial: 30–60, cobrindo os 12 tipos), com objetivo e fontes | Calibração do avaliador humano e exemplos few-shot (apenas do split dev) |
| **Defeitos conhecidos** | Cards com defeito plantado (lista de E§19 + REGRESSION_MAP tipo A), cada um com gabarito do defeito | Medir sensibilidade dos auditores |
| **Afirmações confirmadas** | Claims com evidência conferida por humano | Medir precisão científica do auditor |
| **Casos difíceis e divergências** | Temas com divergência BR × internacional, populações especiais | Robustez |
| **Questões de teste** | Questões do split `EVALUATION` | Teste de transferência/autossuficiência |

Cada conjunto é dividido em **dev** (iterar prompts) e **eval** (estimar desempenho final). O split eval é selado: o código registra cada vez que ele é usado e o relatório mostra quantas vezes foi consultado. Nada é otimizado no eval.

## 2. Defeitos adversariais (mínimo da Fase 5)

Dose errada · unidade trocada (mg/µg) · operador trocado (> / ≥) · diretriz inexistente · referência real que não sustenta a afirmação · contraindicação omitida · recomendação de outra população · tratamento desatualizado · norma revogada como vigente · pergunta ambígua · card redundante · informação essencial no complemento · HTML inválido/script · GUID alterado · correção anterior perdida · cutoff inventado · conduta genérica · card bom (deve receber KEEP).

Métricas por defeito: **detecção** (o auditor apontou o defeito certo, com a gravidade mínima esperada) e **falso alarme** (defeitos apontados em cards limpos; KEEP indevidamente negado).

## 3. Métricas

Primárias (humanas ou derivadas de gabarito, nunca autoavaliação do modelo):
- Taxa de erro crítico por card; precisão científica por afirmação (vs. afirmações confirmadas).
- Detecção de defeitos plantados e taxa de falso alarme dos auditores.
- Taxa de aprovação humana; tempo de revisão humana por card.
- Custo por card aprovado humanamente (US$ e R$).

Secundárias: fundamentação (claims com evidência), números corretos, segurança, completude da resposta essencial, recuperação ativa, granularidade, clareza, aplicabilidade, qualidade visual (avaliação humana cega em escala ordinal com justificativa), referências não verificáveis, truncamento, falhas estruturais, latência.

Sem médias que compensem: relatório mostra cada métrica separadamente e erros críticos em destaque.

## 4. Cegamento

A Mesa de revisão do Laboratório apresenta saídas embaralhadas com rótulos aleatórios; modelo, prompt e custo só são revelados após a decisão humana ser gravada. Avaliador comparativo por IA (se usado) também recebe saídas anônimas e é métrica secundária.

## 5. Protocolo progressivo (Etapa 1 do experimento, orçamento R$15)

1. **Seleção inicial** (sem custo): a partir do catálogo sincronizado, escolher ~6 candidatos por papel cobrindo famílias diferentes (GPT, Claude, Gemini, DeepSeek, GLM, Qwen/Kimi/MiniMax), filtrando por `structured_outputs`, contexto e preço. Lista e custo estimado apresentados ao proprietário para autorização.
2. **Rodada A — triagem barata**: 5 objetivos de um tema-piloto, mesmo contexto/fontes para todos; geração por cada candidato criador; auditoria pelo mesmo auditor fixo. Eliminar quem falha estruturalmente, trunca ou tem erro crítico.
3. **Rodada B — auditores**: os 2–3 melhores auditores científicos candidatos contra o conjunto de defeitos conhecidos (dev).
4. **Rodada C — combinações**: 2–3 pipelines (criador × auditor de famílias diferentes) em 10–15 objetivos; revisão humana cega.
5. **Confirmação no eval**: uma única execução do pipeline escolhido no split eval; resultado registrado como estimativa, com tamanho de amostra e intervalo exato (Clopper-Pearson) para proporções, sem declarar "zero erros" a partir de amostra pequena.

Variantes de prompt (PRM-004): integral, especializado, especializado + exemplos, especializado + contexto recuperado, comparadas na Rodada C com o mesmo modelo.

## 6. Critérios para avançar de etapa (E§28)

Etapa 2 (≈50 cards) → 3 só se: 0 erro crítico não detectado pela auditoria na revisão humana; ≥ 80% dos cards aprovados humanamente sem edição de conteúdo científico (meta a calibrar com o proprietário); custo por card aprovado compatível com o orçamento restante. Caso contrário: análise de falhas e ajuste, sem avançar.

## 7. Registro

Cada execução de benchmark guarda: conjunto e split, versões e hashes de prompt, modelos solicitados e servidos, provedores, parâmetros, fontes, saídas, custos, decisões humanas e data. Resultados são imutáveis e comparáveis entre execuções.
