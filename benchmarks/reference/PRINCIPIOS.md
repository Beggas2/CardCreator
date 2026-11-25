# Princípios extraídos dos cards de referência

Leitura editorial dos 40 cards de referência (20 de escabiose, 20 de doença de Kawasaki), feita em 24/11/2026
junto com `Prompt Criação.txt` e `Prompt Revisor.txt`. O objetivo é entender **por que** os cards funcionam,
para aplicar o raciocínio a conteúdos novos. Não são modelos: nenhum texto, estrutura fixa ou contagem
desses cards deve ser copiado.

Esta leitura **não é auditoria científica**. Não houve verificação contra as fontes. Os pontos da seção 3 são
hipóteses que a auditoria independente (modo `FULL_AUDIT`, com custo autorizado) e a revisão humana confirmam
ou descartam.

## 1. Princípios observados

### Formulação da pergunta
- A frente diz quem, em que forma da doença e segundo qual fonte quando isso muda a resposta ("forma comum
  em adulto imunocompetente", "lactente com menos de 2 meses", "segundo a AHA"). A delimitação está na
  pergunta, não no verso.
- Quando a frente traz duas perguntas, elas formam uma unidade inseparável de recuperação (agente e local
  onde ele vive; esquema e momento de reduzir a dose). Perguntas independentes não são somadas.
- Perguntas de exclusão ("um exame normal exclui...?", "isso exige repetir...?") miram um erro de conduta
  frequente. A resposta curta ("Não") vem com o motivo no complemento.
- Vinhetas clínicas aparecem quando o objetivo é reconhecer ou decidir, não por padrão. São curtas e trazem
  só os dados que discriminam.

### Granularidade e densidade
- Um objetivo por card. Listas ficam entre 3 e 6 itens e só quando o objetivo é a lista em si (critérios,
  locais de exame, grupos de risco).
- Quando a lista tem regra de combinação, a regra está escrita ("≥4 de 5", "≥3 critérios").
- A densidade varia com o objetivo: definição em uma linha, esquema terapêutico em três linhas, critérios
  diagnósticos em lista. Não há tamanho padrão.

### Estrutura adaptativa e separação essencial × explicação
- O essencial responde exatamente à frente e vem primeiro. A explicação, a nuance e a ressalva vão para o
  complemento em cinza, menor. A referência fica numa linha própria, ainda menor.
- O complemento nunca contém algo que a frente exige. Ele traz o "porquê", a exceção clinicamente relevante
  ou a divergência entre fontes.
- O formato acompanha o tipo de conhecimento: cadeia com setas para mecanismo, pares contrastados para
  diferenciar, tabela para classificação por faixas, passos para conduta.

### Semântica das cores
- Azul em negrito: o conceito, diagnóstico ou conduta que deve ser recuperado.
- Âmbar em negrito: números, intervalos e prazos (doses, limiares, dias).
- Vermelho em negrito: risco, contraindicação, sinal de alarme e respostas negativas que evitam dano.
- Negrito só aparece com cor semântica, e só no alvo de recuperação. O texto neutro não é colorido.
- Poucos alvos por card. Quando uma lista inteira é o alvo, o destaque vai para o item ou número que
  discrimina, não para tudo.

### Contexto clínico e precisão numérica
- Número sempre com unidade, operador explícito (≥, <, ≤) e âncora temporal ("após o 7º dia", "após o
  término da infusão", "48 horas afebril").
- Unidade alternativa quando a prática usa as duas (mg/dL e mg/L; µg/kg e mg/kg).
- Ressalva de população e de cenário junto ao número ("em paciente elegível", "em adulto imunocompetente").
- Encaminhamento ("manejo especializado", "com cardiologia pediátrica") quando a decisão não cabe ao
  generalista. O card não finge um protocolo que não existe.

### Rastreabilidade e divergência
- A fonte aparece como instituição e ano, curta, no rodapé.
- Divergência entre fontes é explicitada e atribuída ("SBP: 7 dias; CDC: 7–14 dias"). A norma brasileira é o
  eixo e a internacional aparece identificada. Há card dedicado quando a divergência é o objetivo.

### Diversidade de layouts
- 10 dos 12 tipos cognitivos aparecem (faltam E e K). A distribuição segue os objetivos do tema, não uma cota.

## 2. Como o sistema usa isto

- A política `prompts/policies/editorial.md` resume os princípios acima em regras gerais, sem exemplos copiados.
  Ela entra no criador, no corretor e no auditor pedagógico. É versionada como qualquer prompt e pode ser
  editada ou revertida na tela Prompts.
- Os 40 cards formam o conjunto **Referência** do benchmark (Fase 5). Metade fica no split `dev` e metade no
  `eval`, separadas por tema e com o `eval` selado (cada consulta é registrada).
- Os cards passam pela mesma auditoria que qualquer deck importado. O resultado deles não é presumido.

## 3. Pontos para a auditoria independente (hipóteses, não conclusões)

| Card | Observação | Dimensão |
|---|---|---|
| Kawasaki · limiares de PCR e VHS | Sigla "PCR" sem definição no card (proteína C reativa × parada cardiorrespiratória × reação em cadeia da polimerase). Achado da varredura automática. | Ambiguidade (baixa) |
| Escabiose · localizações em lactentes | A frente diz que as regiões são "habitualmente poupadas em adultos", e o complemento diz que palmas e plantas também podem ser atingidas em adultos. A tensão pode confundir a autoavaliação. | Pedagógica |
| Escabiose · esquema de permetrina | Rodapé cita "SBP 2020" e "SBP 2019" no mesmo card. Conferir se são documentos diferentes ou duplicidade. | Rastreabilidade |
| Escabiose · tratamento na gestação | Rodapé "AAD" sem ano. | Rastreabilidade |
| Vários (13 cards) | Sem linha de referência (ex.: agente etiológico, mecanismo do prurido, fases do Kawasaki). Conferir se a política exige fonte também para conteúdo definicional. | Rastreabilidade |
| Escabiose · ivermectina em menores de 15 kg | Conferir a vigência da restrição por peso nas fontes mais recentes. | Científica (vigência) |
| Kawasaki · critérios de alto risco (AHA 2024) | A frente diz "dois critérios". Conferir na fonte se a lista é de fato restrita a dois. | Científica (completude) |
| Kawasaki · critérios laboratoriais suplementares | Seis itens e cinco números em negrito no mesmo card. Avaliar a carga cognitiva. | Pedagógica |
| Kawasaki · IGIV | O essencial cita "associada a AAS" sem dose (a dose está em outro card). Avaliar se a frente exige a dose. | Pedagógica |
| Escabiose · referências de 2026 | "HU Brasil 2026": conferir o documento e a data. | Rastreabilidade |
