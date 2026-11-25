<!-- Especificação original do proprietário, recebida em 24/11/2026. Texto preservado; referências "E§n" na documentação apontam para as seções abaixo. -->

# CARDFACTORY — Sistema proprietário de produção e auditoria de conhecimento médico em escala

## 1. Missão do projeto

Desenvolver uma aplicação independente, inicialmente local, destinada à produção, expansão, revisão, atualização e validação de flashcards médicos de excelência, com utilização comercial futura no IgorSRS (nome comercial ainda indefinido).

A qualidade dos cards será um dos principais diferenciais competitivos do produto.

O objetivo primário NÃO é maximizar o número de cards produzidos ou minimizar o custo de inferência.

O objetivo é maximizar a quantidade de conhecimento cientificamente correto, compreendido, recuperável, retido e clinicamente aplicável por unidade de tempo de estudo.

O sistema deverá permitir produzir milhares de cards com qualidade igual ou superior àquela obtida atualmente mediante utilização manual do ChatGPT e Claude.

Não considerar essa superioridade demonstrada antes de realizar avaliações comparativas.

A primeira meta experimental é produzir e auditar aproximadamente 1.000 cards utilizando um orçamento total de R$ 100 em serviços de IA e pesquisa.

A quantidade é uma meta flexível. A qualidade não deve ser reduzida para atingir a quantidade.

Posteriormente, pretende-se investir aproximadamente R$ 2.000 para produzir um acervo médico substancialmente maior.

## 2. Documentos normativos obrigatórios

Foram fornecidos dois documentos:

- `Prompt Criação.txt`
- `Prompt Revisor.txt`

Leia integralmente ambos antes de definir a arquitetura.

Esses documentos representam a especificação científica, pedagógica, editorial, visual e técnica desenvolvida pelo proprietário.

Não são meros exemplos de prompts.

São fontes normativas do produto.

Preserve seus arquivos originais, sem modificações, em diretório versionado.

Não descarte regras por considerá-las excessivamente detalhadas.

Não substitua os documentos por resumos genéricos.

Não reduza a qualidade científica ou pedagógica para economizar tokens.

Identifique:

- Requisitos científicos.
- Requisitos pedagógicos.
- Requisitos cognitivos.
- Requisitos visuais.
- Requisitos técnicos.
- Requisitos de integridade.
- Requisitos de cobertura.
- Requisitos de auditoria.
- Requisitos comerciais.
- Operações de manutenção.
- Hierarquia de prioridades.
- Critérios de aprovação.
- Testes de regressão.
- Potenciais inconsistências entre instruções.

Crie uma matriz de rastreabilidade associando cada requisito relevante a:

- Identificador estável.
- Documento e seção de origem.
- Descrição.
- Prioridade.
- Módulo responsável.
- Método de implementação.
- Método de validação.
- Testes correspondentes.
- Status de implementação.

Classifique cada requisito como:

- Executável deterministicamente por código.
- Executável por modelo de IA.
- Dependente de pesquisa externa.
- Dependente de avaliação humana.
- Híbrido.

Em caso de conflito, preserve a hierarquia de segurança, correção científica, vigência, qualidade de aprendizagem, integridade e estética estabelecida nos documentos.

Registre decisões arquiteturais e eventuais ambiguidades.

## 3. Princípios arquiteturais

Desenvolver um sistema modular, local-first, independente de fornecedor de IA.

A aplicação deverá funcionar em Windows, com instalação e inicialização simples.

Priorizar tecnologias maduras e de baixa complexidade operacional.

Stack inicial sugerida:

- Python 3.12 ou versão estável compatível.
- FastAPI.
- Pydantic.
- SQLite com WAL e migrações.
- SQLAlchemy ou alternativa equivalente.
- React e TypeScript.
- Vite.
- Workers locais com fila persistente.
- Sistema local de armazenamento documental.
- Busca textual FTS5.
- Embeddings e índice vetorial local, quando justificados.
- Pytest.
- Playwright.

A stack poderá ser ajustada mediante justificativa técnica.

Evitar microserviços, Kubernetes, Redis obrigatório, infraestrutura distribuída ou serviços pagos desnecessários nesta primeira versão.

Separar:

1. Interface.
2. Backend.
3. Orquestrador.
4. Adaptadores de provedores.
5. Biblioteca científica.
6. Banco de conhecimento.
7. Motor de geração.
8. Motor de auditoria.
9. Motor de renderização.
10. Motor de exportação.
11. Sistema de avaliação.
12. Controle financeiro.

O sistema deverá funcionar com dados simulados sem chave de API, possibilitando desenvolvimento e testes sem despesas.

Não modificar o IgorSRS existente.

A integração futura será realizada mediante contratos versionados de importação e exportação.

## 4. Integração com OpenRouter

Implementar OpenRouter como primeiro provedor.

Consultar a documentação oficial vigente antes da implementação.

Documentação: https://openrouter.ai/docs

Não presumir que recursos disponíveis na interface comercial estejam disponíveis na API.

Implementar uma abstração de provedor que permita futuramente integrar APIs diretas de outras empresas.

Permitir seleção de diferentes modelos para cada etapa.

Considerar famílias:

- OpenAI GPT.
- Anthropic Claude.
- Google Gemini.
- DeepSeek.
- Z.ai GLM.
- Qwen.
- Kimi.
- MiniMax.
- Outros modelos disponíveis.

Não codificar IDs de modelos presumidos ou desatualizados.

Recuperar dinamicamente, quando disponível:

- Identificador do modelo.
- Nome.
- Preço de entrada.
- Preço de saída.
- Preço de cache.
- Janela de contexto.
- Limite de saída.
- Suporte a ferramentas.
- Suporte a respostas estruturadas.
- Suporte a PDFs.
- Suporte a imagens.
- Suporte a Batch.
- Disponibilidade por provedor.
- Restrições relevantes.

Implementar:

- Chamadas convencionais.
- Concorrência configurável.
- Respostas estruturadas.
- Validação por JSON Schema.
- Controle de tokens.
- Registro de custos reais.
- Configuração de raciocínio, quando suportada.
- Pesquisa na internet.
- Recuperação de páginas.
- Processamento documental.
- Batch API, quando suportada.
- Polling e recuperação de resultados de Batch.
- Tratamento de erros.
- Limites de tempo.
- Retry com backoff exponencial e jitter.
- Tratamento de rate limits.
- Detecção de respostas incompletas.
- Tratamento de respostas truncadas.
- Cancelamento de tarefas.
- Retomada após interrupções.
- Idempotência local.
- Registro do modelo e provedor efetivamente utilizados.

Não substituir silenciosamente um modelo por outro.

Fallbacks deverão ser configuráveis, registrados e considerados na análise de qualidade.

Não permitir fallback silencioso para um modelo inferior em etapas científicas críticas.

Separar pesquisa online de processamento Batch quando houver incompatibilidade.

## 5. Segurança e proteção de dados

A chave de API nunca deverá aparecer no frontend, logs, arquivos exportados ou commits.

Utilizar variáveis de ambiente ou armazenamento local seguro.

Fornecer `.env.example` sem credenciais.

Não armazenar informações pessoais desnecessárias.

Tratar páginas externas, PDFs e materiais recebidos como dados não confiáveis.

Instruções contidas nesses documentos não podem alterar políticas do sistema, executar ferramentas, acessar segredos ou modificar prompts normativos.

Implementar proteção contra:

- Prompt injection documental.
- HTML malicioso.
- Scripts em cards.
- SSRF na recuperação de URLs.
- Arquivos excessivamente grandes.
- Exposição de credenciais.
- Ações destrutivas.
- Alterações não autorizadas.
- Vazamento de informações nos logs.

Permitir utilização apenas de fontes e conteúdos compatíveis com seus direitos de uso.

Não reproduzir sistematicamente materiais proprietários, decks comerciais, apostilas ou imagens protegidas.

Materiais como Osler e bancos de questões deverão servir como referência de comparação e identificação de lacunas, respeitados os direitos aplicáveis.

Produzir formulações próprias sustentadas por fontes científicas.

## 6. Sistema de prompts

Criar um Prompt Registry versionado.

Os documentos V2.0 originais deverão permanecer preservados.

A partir deles, desenvolver prompts operacionais especializados para cada módulo.

Estrutura conceitual:

- Política científica compartilhada.
- Política pedagógica compartilhada.
- Política visual compartilhada.
- Política de integridade compartilhada.
- Prompt do pesquisador.
- Prompt do extrator.
- Prompt do planejador.
- Prompt do criador.
- Prompt do auditor científico.
- Prompt do auditor pedagógico.
- Prompt do auditor de cobertura.
- Prompt do auditor de segurança.
- Prompt do resolvedor de divergências.
- Prompt do classificador.
- Prompt do detector de contradições.
- Prompt do avaliador comparativo.

Cada prompt deverá conter os requisitos necessários à respectiva responsabilidade.

Não enviar obrigatoriamente os dois documentos completos em todas as requisições.

Entretanto, toda redução ou modularização deverá preservar a rastreabilidade dos requisitos originais.

Criar verificação de cobertura das regras obrigatórias.

Comparar experimentalmente:

- Prompt integral.
- Prompt especializado.
- Prompt especializado com exemplos selecionados.
- Prompt especializado com contexto científico recuperado.

Não considerar um prompt reduzido equivalente sem avaliação.

Permitir editar, duplicar, restaurar e comparar versões de prompts pela interface.

Registrar em cada execução:

- Versão do prompt.
- Hash.
- Modelo.
- Configuração.
- Fontes.
- Objetivos.
- Resultado.
- Custo.

Uma alteração de prompt não deverá modificar retroativamente os registros anteriores.

## 7. Modos de funcionamento

Implementar progressivamente os modos previstos nos documentos V2.0.

### Criação

- Criação integral de novo deck.
- Expansão de deck existente.
- Atualização científica.
- Reformatação cognitiva e visual.
- Reconstrução integral.
- Complementação por provas.

### Revisão

- Auditoria integral.
- Auditoria científica.
- Auditoria de cobertura.
- Auditoria cognitiva.
- Migração visual.
- Auditoria técnica.
- Auditoria de regressão.
- Segunda opinião independente.
- Auditoria orientada pelo desempenho.

Na primeira versão operacional, priorizar criação integral, expansão e auditoria integral.

Os demais modos devem possuir arquitetura prevista, sem necessidade de implementação superficial ou fictícia.

## 8. Biblioteca científica dinâmica

O usuário NÃO deverá ser obrigado a fornecer PDFs.

Implementar três modalidades:

A. Pesquisa científica autônoma.

B. Produção baseada em documentos enviados.

C. Produção híbrida, padrão recomendado.

Na modalidade híbrida, os documentos fornecidos complementam a pesquisa, mas não substituem a verificação científica.

O sistema deverá pesquisar autonomamente documentos relevantes.

Priorizar:

- Ministério da Saúde.
- PCDTs.
- SUS.
- Sociedades brasileiras de especialidade.
- Normas oficiais.
- Consensos brasileiros.
- Fontes internacionais reconhecidas, quando aplicáveis.
- Revisões sistemáticas.
- Estudos primários pertinentes.

Seguir integralmente as regras de hierarquia, especificidade, vigência, divergência e aplicabilidade estabelecidas nos prompts originais.

Implementar busca por:

- Tema.
- Entidade clínica.
- Instituição.
- Documento.
- Ano.
- Versão.
- Domínio.
- População.
- Tipo de evidência.
- Objetivo de aprendizagem.

Não considerar uma pesquisa concluída simplesmente porque o modelo retornou uma lista de referências.

Recuperar efetivamente os documentos ou páginas necessários.

Trechos de mecanismos de busca não são confirmação suficiente de recomendações críticas.

Para cada fonte, armazenar:

- Identificador.
- Título confirmado.
- Instituição.
- URL.
- DOI, quando existente.
- Data de publicação.
- Versão.
- Data de acesso.
- Tipo de documento.
- População.
- Contexto.
- Status de vigência.
- Hash do documento, quando disponível.
- Licença ou restrição conhecida.
- Status de acesso.
- Seções.
- Páginas.
- Tabelas.
- Algoritmos.
- Trechos de evidência autorizados.
- Relação com versões anteriores.

Distinguir claramente:

- Documento encontrado.
- Documento recuperado.
- Documento parcialmente lido.
- Documento efetivamente conferido.
- Documento indisponível.
- Documento desatualizado.
- Documento com vigência incerta.

Não inventar títulos, páginas, DOI, seções ou referências.

Implementar processamento de PDFs textuais e escaneados, incluindo tabelas quando necessário.

Se uma tabela não puder ser interpretada confiavelmente, registrar pendência.

Utilizar OCR ou modelos multimodais seletivamente.

Não enviar novamente documentos inteiros em todas as chamadas.

Criar um sistema de recuperação de evidências por relevância, com busca híbrida textual e semântica.

Recuperar seções completas quando o contexto for indispensável.

Não perder condições, rodapés, unidades ou exceções importantes devido à fragmentação de documentos.

Implementar cache de pesquisa e reutilização de fontes já verificadas.

Registrar limitações e impedir aprovação de afirmações críticas não verificadas.

## 9. Banco estruturado de conhecimento

Não utilizar o HTML como representação primária dos cards.

Criar um banco de conhecimento intermediário.

Estruturar:

- Entidades clínicas.
- Conceitos.
- Objetivos de aprendizagem.
- Relações entre conceitos.
- Pontos de decisão.
- Afirmações científicas.
- Evidências.
- Divergências.
- Questões relacionadas.
- Cards.
- Versões.
- Auditorias.
- Pendências.
- Operações de manutenção.

Cada afirmação científica deverá possuir identidade própria.

Exemplo: uma recomendação terapêutica pode possuir afirmações relacionadas à indicação, dose, via, intervalo, duração, contraindicação e população.

Esses componentes devem ser verificáveis individualmente.

Uma fonte que confirma a indicação não confirma automaticamente todos os demais componentes.

Registrar associação entre afirmação e evidência.

A relação deve permitir rastrear uma futura alteração de diretriz até todos os cards potencialmente afetados.

Não exigir um grafo de conhecimento sofisticado no MVP se um modelo relacional atender adequadamente aos requisitos.

## 10. Planejamento de cobertura

Antes de gerar cards:

1. Delimitar o escopo.
2. Pesquisar fontes.
3. Construir o mapa ideal do tema.
4. Identificar entidades clínicas.
5. Definir subdecks.
6. Mapear dimensões aplicáveis.
7. Identificar dependências conceituais.
8. Identificar pontos de decisão clínica.
9. Elaborar objetivos de aprendizagem.
10. Associar evidências.
11. Comparar com a coleção existente.
12. Analisar questões disponíveis.
13. Priorizar objetivos.
14. Definir a quantidade necessária de cards.

Utilizar as dimensões de conhecimento dos documentos V2.0.

Não obrigar todas as dimensões em temas aos quais não se aplicam.

O deck deve nascer da estrutura do conhecimento médico.

As provas deverão servir para validação, priorização e identificação de lacunas, e não como única definição do conteúdo.

Cada objetivo deverá possuir:

- Identificador.
- Área.
- Entidade.
- Subtema.
- Tipo de conhecimento.
- Descrição.
- Relevância clínica.
- Relevância para provas.
- Dependências.
- Fontes.
- Cards existentes.
- Cards planejados.
- Estado de cobertura.

Estados de cobertura conforme os documentos normativos.

Não gerar cards desnecessários para cumprir metas numéricas.

Permitir relatório de cobertura com denominador explícito.

## 11. Geração de cards

Gerar cards em lotes configuráveis.

Valor inicial sugerido: 20 cards.

Permitir ajustar quantidade conforme:

- Complexidade.
- Capacidade do modelo.
- Tamanho do contexto.
- Limite de saída.
- Taxa de falhas.
- Qualidade observada.
- Orçamento.

Antes da geração, reservar os objetivos de aprendizagem atribuídos ao lote.

Evitar que lotes paralelos produzam o mesmo conhecimento sem finalidade pedagógica distinta.

Fornecer ao modelo:

- Objetivos do lote.
- Evidências pertinentes.
- Regras científicas.
- Regras pedagógicas.
- Regras de granularidade.
- Exemplos relevantes.
- Contexto mínimo da coleção.
- Cards semanticamente relacionados.
- Contrato estruturado de saída.

Não obrigar o modelo a escrever HTML diretamente como fluxo principal.

Gerar representação estruturada semelhante a:

```json
{
  "schema_version": "2.0",
  "card_id": "stable_internal_id",
  "anki_guid": null,
  "objective_ids": [],
  "deck_path": [],
  "front": {
    "text": "Pergunta"
  },
  "answer": [
    {
      "role": "essential",
      "type": "direct_answer",
      "content": [
        {
          "text": "Resposta",
          "semantic": "concept",
          "retrieval_target": true,
          "claim_ids": []
        }
      ]
    }
  ],
  "layout": "direct",
  "tags": [],
  "claims": [],
  "source_ids": [],
  "validation_status": "pending"
}
```

O esquema apresentado é conceitual e deverá ser refinado.

Preservar os 12 tipos cognitivos dos prompts V2.0:

A. Resposta direta.

B. Lista.

C. Critérios e classificações.

D. Comparação.

E. Escore ou fórmula.

F. Mecanismo ou fisiopatologia.

G. Conduta ou algoritmo.

H. Farmacologia.

I. Caso clínico.

J. Negativa ou contraindicação.

K. Imagem ou reconhecimento espacial.

L. Integração e transferência.

Preservar a flexibilidade de granularidade.

Não transformar todos os conhecimentos em perguntas de uma única palavra.

Não transformar todos os cards em casos clínicos.

Não transformar o verso em apostila.

Não dividir esquemas terapêuticos, critérios ou informações interdependentes quando isso comprometer compreensão ou segurança.

O objetivo é uma unidade coerente de recuperação.

Implementar as três camadas do verso:

1. Resposta essencial.
2. Compreensão.
3. Complemento.

A resposta essencial deverá conter tudo aquilo que o estudante precisa recuperar para acertar o card.

Não esconder informações obrigatórias ou de segurança em comentários secundários.

Não adicionar explicações decorativas ou redundantes.

## 12. Motor de renderização visual

Implementar renderização determinística, separada da geração científica.

O modelo define:

- Função semântica.
- Camada pedagógica.
- Alvo de recuperação.
- Layout.
- Agrupamento.
- Necessidade de tabela, lista ou algoritmo.

O software aplica o padrão visual.

Paleta V2.0:

- Fundo de referência: `#101114`.
- Branco suave: `#E5E7EB`.
- Cinza-azulado: `#94A3B8`.
- Azul-ciano: `#7DD3FC`.
- Âmbar: `#FCD34D`.
- Vermelho suave: `#FCA5A5`.
- Separadores: `#30343B`.

Semântica:

- Azul: resposta nuclear neutra, conceitos, diagnóstico e conduta.
- Âmbar: doses, valores decisivos, critérios, metas e intervalos relevantes.
- Vermelho: contraindicações, toxicidades, riscos e alertas de segurança.
- Branco: texto neutro e explicações.
- Cinza: conteúdo complementar e referências.

Negrito representa alvo de recuperação.

Tamanho representa hierarquia.

Espaçamento representa agrupamento.

Posição representa ordem de processamento.

Alinhamento representa fluidez.

Não utilizar verde ou lavanda como categorias do padrão V2.0.

Não obrigar todas as cores em todos os cards.

Aplicar as regras completas de tipografia, acessibilidade, ergonomia, alinhamento, listas, tabelas e espaçamento dos documentos originais.

Criar componentes reutilizáveis para os 12 tipos cognitivos.

Implementar preview interativo:

- Frente.
- Verso.
- Revelação da resposta.
- Desktop.
- Celular.
- Modo escuro.
- Modo claro com contraste adequado, quando suportado.

Gerar HTML independente, compatível com Anki, sem JavaScript ou recursos externos.

Implementar testes visuais e snapshots.

## 13. Auditoria científica independente

O revisor não deve confiar na validação declarada pelo criador.

Preferencialmente utilizar modelo de família diferente para geração e auditoria científica.

O auditor deverá receber:

- Card.
- Objetivo.
- Afirmações.
- População.
- Contexto.
- Evidências originais pertinentes.

Evitar fornecer avaliações positivas anteriores antes da auditoria independente.

Verificar cada afirmação relevante.

Classificações:

- Confirmada.
- Incorreta.
- Desatualizada.
- Incompleta.
- Ambígua.
- Dependente do contexto.
- Divergente.
- Não verificada.
- Não aplicável.

Implementar passagens específicas para:

- Fatos e definições.
- Valores numéricos.
- Farmacologia.
- Condutas.
- Contraindicações.
- Populações especiais.
- Vigência.
- Divergências.
- Contradições.
- Rastreabilidade.

Permitir nova pesquisa independente quando a evidência fornecida for insuficiente.

Uma citação válida precisa sustentar a afirmação exata.

Não utilizar concordância entre modelos como prova de verdade científica.

Não gerar porcentagens artificiais de confiança.

Classificar defeitos por gravidade:

- Crítica.
- Alta.
- Média.
- Baixa.
- Observação.

Defeitos críticos não resolvidos bloqueiam liberação.

Afirmações clínicas críticas não verificadas devem ser colocadas em quarentena.

## 14. Auditoria pedagógica

Implementar avaliação independente dos seguintes aspectos:

- Clareza do objetivo.
- Independência contextual.
- Recuperação ativa.
- Precisão da autoavaliação.
- Granularidade.
- Carga cognitiva.
- Redundância.
- Compreensão causal.
- Discriminação.
- Transferência.
- Aplicação clínica.
- Adequação do tipo cognitivo.
- Clareza da frente.
- Completude da resposta essencial.
- Utilidade dos complementos.
- Consistência visual.
- Ergonomia.

Utilizar os critérios detalhados dos documentos V2.0.

Não considerar automaticamente que um card mais curto é melhor.

Não considerar automaticamente que um card mais longo é completo.

Não penalizar dificuldade intrínseca legítima.

Não produzir alterações cosméticas indiscriminadas.

Implementar o princípio da intervenção mínima suficiente.

## 15. Auditoria independente de cobertura

A completude não pode ser avaliada apenas pelo mesmo mapa produzido pelo criador.

Construir um mapa ideal independente, utilizando fontes científicas e o escopo original.

Comparar:

- Mapa do criador.
- Mapa independente.
- Objetivos planejados.
- Objetivos contemplados.
- Cards existentes.
- Questões disponíveis.
- Pontos de decisão.
- Cenários clínicos.

Classificar lacunas.

Identificar:

- Objetivos ausentes.
- Objetivos parcialmente contemplados.
- Conhecimentos incorretos.
- Conhecimentos desatualizados.
- Conhecimentos contemplados em outro deck.
- Dimensões não verificáveis.
- Redundâncias úteis.
- Redundâncias desnecessárias.

Implementar teste de autossuficiência do deck.

Utilizar questões e casos clínicos para verificar se os conhecimentos presentes permitem aplicação, e não apenas recuperação factual.

Não apresentar cobertura integral se materiais necessários estiverem indisponíveis.

## 16. Resolução de divergências e correções

Quando houver defeitos:

1. Identificar o problema.
2. Classificar gravidade.
3. Localizar evidência.
4. Definir a operação apropriada.
5. Corrigir seletivamente.
6. Reauditar a versão modificada.
7. Verificar regressões.
8. Atualizar o registro.

Utilizar operações previstas no Revisor V2.0:

- KEEP.
- UPDATE_CONTENT.
- UPDATE_FRONT.
- UPDATE_PEDAGOGY.
- UPDATE_STYLE.
- MOVE.
- CREATE.
- SPLIT.
- MERGE_REVIEW.
- REVIEW_DELETE.
- QUARANTINE.
- REVIEW_REQUIRED.

Não reescrever automaticamente cards adequados.

Não permitir loops infinitos de correção.

Implementar limite de tentativas, inicialmente duas correções automáticas por defeito, configurável.

Quando persistir divergência científica:

- Recuperar novas evidências.
- Consultar modelo independente, quando justificado.
- Registrar versões concorrentes.
- Encaminhar para decisão humana.

Não resolver divergências por simples votação majoritária entre modelos.

## 17. Deduplicação e consistência global

Implementar múltiplas camadas:

1. Hash exato.
2. Normalização textual.
3. Similaridade lexical.
4. Similaridade semântica.
5. Identidade do objetivo.
6. Comparação das afirmações.
7. Comparação de população e cenário.
8. Auditoria de contradições.

Embeddings deverão identificar candidatos, não determinar automaticamente exclusão.

Distinguir:

- Duplicação verdadeira.
- Repetição pedagogicamente útil.
- Aplicação em novo contexto.
- Card integrador.
- Contraste.
- Contradição.
- Divergência legítima entre diretrizes.

Comparar com toda a coleção importada, inclusive outros subdecks.

Preservar a propriedade principal do conhecimento.

Não excluir registros automaticamente.

Não criar contradições artificiais entre recomendações válidas para populações diferentes.

## 18. Questões de residência

Preparar integração com o banco de questões e o futuro classificador compartilhado com IgorSRS.

Inicialmente permitir importação de arquivos de questões.

Registrar:

- Banca.
- Ano.
- Instituição.
- Prova.
- Identificador.
- Enunciado, quando autorizado.
- Alternativas.
- Gabarito preliminar.
- Gabarito definitivo.
- Anulação.
- Fonte.
- Objetivos exigidos.
- Conhecimentos necessários.
- Conhecimentos envolvidos nas alternativas incorretas.
- Cards relacionados.
- Estado de cobertura.

A análise científica não deve aceitar o gabarito como autoridade médica.

Identificar questões desatualizadas ou controversas.

Permitir medir incidência real com denominador e escopo explícitos.

Não inventar frequência de cobrança.

Não alegar cobertura de provas não importadas ou não conferidas.

Separar questões destinadas ao planejamento de questões reservadas para avaliação.

## 19. Sistema de avaliação e benchmark

Criar um módulo independente de avaliação de modelos, prompts e pipelines.

Não assumir antecipadamente qual IA é superior.

Criar um conjunto de referência com exemplos de cards excelentes fornecidos pelo proprietário.

Permitir adicionar:

- Cards bons.
- Cards ruins.
- Defeitos conhecidos.
- Afirmações confirmadas.
- Casos difíceis.
- Divergências científicas.
- Questões de teste.
- Correções humanas.

Registrar resultados de maneira cega quanto à origem, quando possível.

Avaliar:

- Precisão científica.
- Fundamentação.
- Correção dos valores numéricos.
- Segurança.
- Completude.
- Recuperação ativa.
- Granularidade.
- Clareza.
- Aplicabilidade.
- Qualidade da resposta essencial.
- Qualidade visual.
- Taxa de aprovação humana.
- Tempo de revisão humana.
- Custo por card aprovado.
- Latência.
- Taxa de truncamento.
- Taxa de falhas estruturais.
- Taxa de referências não verificáveis.
- Taxa de erros críticos.

Não utilizar autoavaliação do modelo como métrica primária.

Implementar testes adversariais com erros conhecidos.

Exemplos:

- Dose propositalmente incorreta.
- Unidade trocada.
- Diretriz inexistente.
- Referência real que não sustenta a afirmação.
- Contraindicação omitida.
- Recomendação de população diferente.
- Tratamento desatualizado.
- Pergunta ambígua.
- Card redundante.
- Informação essencial relegada ao complemento.
- HTML inválido.
- Alteração indevida de GUID.
- Correção anterior perdida.

Separar conjuntos de desenvolvimento e avaliação.

Não otimizar prompts repetidamente sobre o mesmo conjunto usado para estimar desempenho final.

Permitir comparar diferentes modelos nas mesmas condições, com as mesmas fontes e objetivos.

Não declarar ausência absoluta de erros a partir de uma amostra limitada.

## 20. Controle de custos

Esta funcionalidade é obrigatória antes de qualquer produção real.

Implementar orçamento por:

- Projeto.
- Execução.
- Etapa.
- Modelo.
- Lote.
- Experimento.

Orçamento inicial: R$ 100, incluindo margem para taxas, câmbio e serviços adicionais de pesquisa ou processamento.

Registrar valores em moeda original e em reais conforme câmbio configurado.

Implementar:

- Estimativa de custo antes da execução.
- Limite máximo de tokens.
- Limite de pesquisas.
- Limite de ferramentas.
- Limite de correções.
- Limite de concorrência.
- Reserva financeira para chamadas em andamento.
- Controle de despesas já confirmadas.
- Reconciliação de despesas pendentes.
- Registro de custos de requisições com falha, quando cobradas.
- Custos de Batch.
- Custos de embeddings.
- Custos de parsing e OCR, quando cobrados.
- Custo por objetivo.
- Custo por card gerado.
- Custo por card auditado.
- Custo por card aprovado pela IA.
- Custo por card aprovado humanamente.

Antes de iniciar nova chamada, verificar:

`Gasto confirmado + gasto reservado + custo máximo estimado da nova chamada <= orçamento disponível`.

Realizar reserva atomicamente para evitar excesso de gastos por concorrência.

Se o custo não puder ser estimado com segurança, bloquear a execução ou exigir confirmação.

Ao atingir limite configurado, pausar novas chamadas e preservar o estado.

Implementar limites adicionais na própria chave do provedor, quando disponíveis.

Não confiar exclusivamente no limite do provedor, pois podem existir chamadas simultâneas e custos ainda não reconciliados.

O sistema não poderá comprar créditos, aumentar limites ou trocar para serviços mais caros automaticamente.

## 21. Orquestrador persistente

Implementar uma máquina de estados persistente.

Fluxo conceitual:

1. Inventário.
2. Pesquisa.
3. Recuperação documental.
4. Extração.
5. Planejamento.
6. Construção de objetivos.
7. Geração.
8. Auditoria científica.
9. Auditoria pedagógica.
10. Auditoria de cobertura.
11. Correções.
12. Reauditoria.
13. Deduplicação.
14. Validação técnica.
15. Revisão humana.
16. Exportação.

Cada tarefa deverá possuir:

- ID.
- Dependências.
- Estado.
- Prioridade.
- Entrada.
- Saída.
- Tentativas.
- Erros.
- Versão de prompt.
- Modelo.
- Provedor.
- Tokens.
- Custo.
- Horários.
- Checkpoint.

Permitir:

- Iniciar.
- Pausar.
- Retomar.
- Cancelar.
- Reprocessar uma etapa.
- Reprocessar um lote.
- Reprocessar um card.
- Reutilizar resultados válidos.
- Inspecionar erros.
- Exportar execução parcial.

O encerramento do aplicativo não deverá perder resultados já concluídos.

Não repetir automaticamente uma chamada potencialmente cobrada quando sua situação for incerta.

Persistir identificadores de jobs remotos.

Não depender da memória conversacional da IA.

Utilizar identificadores, registros e estados explícitos.

Não considerar um deck concluído quando houver tarefas obrigatórias pendentes.

## 22. Interface

Criar interface desktop web local, responsiva, dark-first.

Priorizar ergonomia, produtividade e clareza.

Telas principais:

### Dashboard

- Cards gerados.
- Cards auditados.
- Cards aprovados.
- Cards em quarentena.
- Cards pendentes.
- Objetivos contemplados.
- Execuções ativas.
- Gastos.
- Custo médio.
- Indicadores de qualidade.

### Nova produção

Permitir configurar:

- Área.
- Tema.
- Escopo.
- Profundidade.
- Quantidade desejada.
- Orçamento.
- Coleção existente.
- Taxonomia.
- Pesquisa autônoma.
- PDFs complementares.
- Provas.
- Fontes preferenciais.
- Modelos por etapa.
- Tamanho dos lotes.
- Concorrência.
- Perfil pedagógico.

Apresentar plano estimado antes de gastar créditos.

### Biblioteca científica

- Fontes.
- Versões.
- Documentos.
- Trechos.
- Evidências.
- Status.
- Busca.
- Divergências.
- Cards afetados.

### Mapa de conhecimento

- Entidades.
- Objetivos.
- Dependências.
- Subdecks.
- Cobertura.
- Lacunas.
- Prioridades.

### Monitor de execução

- Pipeline.
- Etapas.
- Lotes.
- Progresso.
- Erros.
- Tokens.
- Gastos.
- Tentativas.
- Pausa e retomada.

### Mesa de revisão

Interface especialmente otimizada para revisar centenas de cards.

Exibir:

- Frente.
- Verso renderizado.
- Objetivo.
- Afirmações.
- Evidências.
- Documento e seção pertinentes.
- Auditorias.
- Defeitos.
- Divergências.
- Versões anteriores.
- Cards semelhantes.

Permitir:

- Aprovar.
- Reprovar.
- Editar.
- Solicitar nova pesquisa.
- Solicitar correção.
- Colocar em quarentena.
- Comparar versões.
- Desfazer.
- Navegar por teclado.
- Filtrar por gravidade.
- Filtrar por tema.
- Filtrar por modelo.
- Filtrar por status.

A aprovação humana não deve ser confundida com aprovação automatizada.

### Laboratório de modelos

- Comparar modelos.
- Comparar prompts.
- Executar benchmark.
- Avaliação cega.
- Inspecionar métricas.
- Comparar custos.
- Comparar erros.

### Editor de prompts

- Visualizar.
- Editar.
- Duplicar.
- Versionar.
- Comparar.
- Restaurar.
- Ver requisitos normativos associados.

### Exportação

- Anki.
- JSON estruturado.
- Manifestos.
- Relatórios.
- Pendências.
- Backup.
- Formato futuro IgorSRS.

## 23. Integridade, identidade e histórico

Cada card deverá possuir identidade interna estável.

Distinguir identidade interna do GUID Anki.

Preservar GUIDs originais quando o objetivo de aprendizagem permanecer equivalente.

Alterações substanciais de objetivo deverão ser tratadas explicitamente.

Implementar:

- Versionamento de cards.
- Histórico de operações.
- Diferenças entre versões.
- Backup.
- Rollback.
- Registro de autoria humana ou IA.
- Registro de correções anteriores.
- Auditoria de regressão.
- Estado final simulado.

Não modificar o scheduler.

Não alterar intervalos, histórico de revisões ou estados de memória.

Não excluir diretamente notas da coleção Anki.

Movimentações, fusões e exclusões deverão ser propostas e registradas conforme os documentos normativos.

## 24. Exportação

Implementar formato principal V2.0:

- UTF-8 sem BOM.
- Separador por tabulação.
- Uma linha física por nota.
- Serializador confiável.
- HTML independente.

Cabeçalhos:

```text
#separator:tab
#html:true
#guid column:1
#notetype column:2
#deck column:3
#tags column:6
```

Colunas:

1. GUID.
2. Tipo de nota.
3. Deck.
4. Frente.
5. Verso.
6. Tags.

Implementar formato simplificado opcional:

`Frente;Verso`

Preservar o tipo de nota existente ou Basic, quando aplicável.

Implementar arquivos de entrega previstos nos documentos originais, conforme o modo executado.

Incluir:

- Deck validado.
- Atualizações.
- Deck completo revisado.
- Pendências.
- Manifesto de exclusões propostas.
- Manifesto de movimentações.
- Backups.
- Relatório.
- JSON estruturado.
- Manifesto de fontes.

Não produzir arquivos vazios desnecessários.

Implementar teste de round-trip de serialização.

Conferir contagem, GUIDs, HTML, tags e correspondência dos registros.

Testar importação em coleção Anki descartável quando tecnicamente possível.

Não alegar teste de importação quando apenas a serialização tiver sido testada.

A integração IgorSRS deverá utilizar contratos versionados definidos posteriormente, sem alterar o aplicativo existente.

## 25. Atualização contínua

Preparar arquitetura para:

- Detectar novas versões de fontes.
- Comparar recomendações.
- Identificar afirmações afetadas.
- Identificar cards afetados.
- Priorizar mudanças de segurança.
- Solicitar auditoria localizada.
- Gerar propostas de atualização.
- Preservar histórico.
- Publicar versões corrigidas.

Não alterar cards automaticamente apenas porque uma nova publicação foi encontrada.

Validar a vigência, aplicabilidade e relevância da mudança.

## 26. Aprendizado editorial

Registrar decisões humanas estruturadamente.

Exemplos:

- Card aprovado.
- Pergunta ambígua.
- Resposta excessivamente longa.
- Fragmentação inadequada.
- Falta de mecanismo.
- Informação complementar irrelevante.
- Erro científico.
- Fonte inadequada.
- Layout inadequado.
- Duplicação.
- Ausência de contextualização.

Permitir utilizar exemplos de correções em futuras gerações.

Implementar recuperação seletiva de exemplos semelhantes.

Não permitir que o sistema modifique automaticamente políticas científicas ou prompts normativos sem aprovação.

Inicialmente não realizar fine-tuning.

Priorizar prompts especializados, exemplos relevantes, evidências recuperadas e avaliação objetiva.

## 27. Critérios de liberação

Separar estados:

- Rascunho.
- Gerado.
- Em auditoria.
- Corrigido.
- Aprovado automaticamente.
- Pendente de revisão humana.
- Aprovado humanamente.
- Reprovado.
- Quarentena.
- Pronto para exportação.
- Liberado comercialmente.
- Desatualizado.

Não utilizar pontuação média para compensar erros médicos.

Bloquear liberação quando houver:

- Defeito científico crítico conhecido.
- Afirmação clínica crítica não verificada.
- Referência inventada.
- Contradição relevante não resolvida.
- Erro de identidade.
- Erro técnico bloqueante.
- Problema de direitos de utilização.
- Revisão humana obrigatória pendente.

Para o lote experimental, exigir revisão humana de todos os cards destinados à publicação.

Não apresentar aprovação automática como certificação médica.

## 28. Experimento inicial de R$ 100

Implementar um protocolo experimental progressivo.

### Etapa 0 — Validação sem gastos

- Testes com mocks.
- Testes de pipeline.
- Testes de retomada.
- Testes de orçamento.
- Testes de segurança.
- Testes de importação e exportação.
- Testes de renderização.
- Testes de auditoria com defeitos conhecidos.

### Etapa 1 — Microbenchmark

Comparar pequeno conjunto de objetivos entre diferentes modelos.

Avaliar, inicialmente, combinações de GPT, Claude, Gemini, DeepSeek, GLM e outros modelos economicamente interessantes.

Não testar todas as combinações possíveis.

Usar seleção progressiva dos candidatos mais promissores.

Limitar o gasto.

### Etapa 2 — Primeiro lote

Gerar aproximadamente 50 cards.

Realizar pesquisa, auditorias, correções e revisão humana.

Analisar falhas antes de prosseguir.

### Etapa 3 — Lote intermediário

Gerar aproximadamente 200 cards adicionais, ou quantidade ajustada conforme os resultados.

Avaliar consistência entre lotes, custo e qualidade.

### Etapa 4 — Produção ampliada

Buscar completar aproximadamente 1.000 cards únicos, respeitando o orçamento restante e os critérios de qualidade.

Não gastar o orçamento integral antecipadamente.

Não prosseguir automaticamente para a etapa seguinte quando os critérios de qualidade não forem atingidos.

Distribuição financeira inicialmente sugerida:

- Pesquisa e planejamento: R$ 10.
- Benchmark: R$ 15.
- Geração: R$ 20.
- Auditoria científica: R$ 25.
- Auditoria pedagógica: R$ 10.
- Classificação e deduplicação: R$ 5.
- Reserva e correções: R$ 15.

Essa divisão é configurável, não uma obrigação de consumo.

O sistema deverá propor realocação quando necessário, sujeita à aprovação.

A meta final não é produzir 1.000 registros brutos.

É produzir aproximadamente 1.000 cards úteis, únicos, auditáveis e aprováveis.

## 29. Testes obrigatórios

Implementar testes unitários, integração e E2E conforme as responsabilidades.

Incluir:

- Schemas.
- Serialização.
- GUIDs.
- HTML.
- Paleta.
- Renderização.
- Importação.
- Exportação.
- Deduplicação.
- Contradições.
- Versionamento.
- Regressão.
- Mapeamento de objetivos.
- Rastreabilidade.
- Respostas inválidas.
- Respostas truncadas.
- Falhas do provedor.
- Rate limits.
- Fallback.
- Retomada.
- Cancelamento.
- Idempotência.
- Concorrência.
- Orçamento.
- Reserva de custos.
- Vazamento de segredos.
- Prompt injection.
- Quarentena.
- Aprovação humana.
- Operações não destrutivas.

Utilizar os validadores e testes de regressão descritos nos documentos V2.0 como referência obrigatória.

Nenhum teste automatizado deverá gastar créditos reais por padrão.

Implementar fixtures e provedores simulados.

## 30. Ordem de implementação

### Fase 0 — Especificação e arquitetura

- Leitura integral dos prompts.
- Matriz de requisitos.
- Identificação de ambiguidades.
- Arquitetura.
- Modelo de dados.
- Contratos.
- Planejamento.
- Critérios de aceitação.

### Fase 1 — Fundação

- Estrutura do projeto.
- Banco de dados.
- Migrações.
- Adaptador OpenRouter.
- Provedor simulado.
- Prompt Registry.
- Orquestrador persistente.
- Controle financeiro.
- Interface inicial.

### Fase 2 — Pesquisa e conhecimento

- Biblioteca científica.
- Importação de documentos.
- Pesquisa.
- Recuperação.
- Evidências.
- Mapa de conhecimento.
- Objetivos.

### Fase 3 — Geração e renderização

- Schemas.
- Geração em lotes.
- Renderização cognitiva.
- Preview.
- Versionamento.
- Exportação.

### Fase 4 — Auditoria

- Auditor científico.
- Auditor pedagógico.
- Auditor de cobertura.
- Correção.
- Reauditoria.
- Deduplicação.
- Quarentena.
- Regressão.

### Fase 5 — Revisão e benchmark

- Mesa de revisão.
- Avaliação cega.
- Comparação entre modelos.
- Métricas de qualidade.
- Relatórios.

### Fase 6 — Experimento

- Execução controlada de testes reais, somente após autorização financeira.
- Lote inicial.
- Avaliação.
- Ajustes.
- Ampliação progressiva.

Não implementar funcionalidades fictícias apenas para marcar etapas como concluídas.

Priorizar fluxos completos e funcionais.

## 31. Documentação

Manter:

- README.
- AGENTS.md.
- ARCHITECTURE.md.
- REQUIREMENTS.md.
- REQUIREMENTS_TRACEABILITY.md.
- DATA_MODEL.md.
- PIPELINE.md.
- PROMPT_REGISTRY.md.
- QUALITY_POLICY.md.
- BENCHMARK_PROTOCOL.md.
- COST_CONTROL.md.
- SECURITY.md.
- IMPLEMENTATION_PLAN.md.
- STATUS.md.

Registrar decisões arquiteturais relevantes em ADRs.

Documentar instalação, inicialização, configuração, testes e recuperação de falhas.

Manter instruções claras para continuidade por outros agentes de desenvolvimento.

## 32. Instrução inicial ao agente de desenvolvimento

Não comece gerando centenas de cards.

Não faça chamadas pagas sem autorização expressa.

Não modifique o IgorSRS.

Primeiramente:

1. Leia integralmente os dois prompts fornecidos.
2. Analise suas responsabilidades e requisitos.
3. Consulte a documentação atual do OpenRouter.
4. Identifique capacidades e limitações reais da API.
5. Construa a matriz de rastreabilidade.
6. Defina a arquitetura proposta.
7. Defina o modelo de dados.
8. Defina os contratos entre módulos.
9. Defina o protocolo de benchmark.
10. Defina o mecanismo de controle financeiro.
11. Produza o plano de implementação.
12. Implemente a fundação em etapas verificáveis, com testes.

Não solicite confirmação para decisões técnicas rotineiras e reversíveis.

Solicite autorização antes de gastos reais, alterações destrutivas ou decisões que modifiquem requisitos normativos.

Ao final de cada fase, registre:

- O que foi implementado.
- O que foi efetivamente testado.
- Resultados dos testes.
- Limitações.
- Pendências.
- Decisões tomadas.
- Próxima etapa.
- Custos, quando existirem.

O produto deverá ser projetado para excelência editorial e científica em escala, sem sacrificar confiabilidade em favor de velocidade ou economia.

A qualidade deverá ser demonstrada, não apenas declarada.
