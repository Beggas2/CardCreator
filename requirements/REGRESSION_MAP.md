# REGRESSION_MAP — Falhas históricas → testes de regressão

Origem: `Prompt Criação.txt` §40 (C01–C64) e `Prompt Revisor.txt` §54 (R01–R82).
Cada falha vira um caso permanente. Tipo de teste:

- **U** = teste unitário determinístico (pytest, sem IA, roda sempre).
- **A** = fixture adversarial do benchmark (card com defeito plantado; o pipeline de auditoria precisa detectá-lo). Roda contra o provedor simulado na CI (verifica fiação e regras) e contra modelos reais só em benchmark autorizado.
- **H** = item de checklist da revisão humana (não automatizável com segurança).
- **P** = verificação de processo (o orquestrador/relatório impede a declaração sem execução).

## Criador §40

| # | Falha | Tipo | Teste |
|---|---|---|---|
| C01 | Entidades HTML corrompidas na serialização | U | reg_C01_html_entities_round_trip |
| C02 | Aspas duplas truncando campos | U | reg_C02_double_quotes |
| C03 | Notas fantasmas por delimitadores | U | reg_C03_phantom_notes |
| C04 | `<`/`>` de comparação interpretados como HTML | U | reg_C04_comparison_chars |
| C05 | BOM | U | reg_C05_no_bom |
| C06 | Cor fora da paleta | U | reg_C06_palette |
| C07 | GUID reutilizado | U | reg_C07_guid_unique |
| C08 | Número incorreto de colunas | U | reg_C08_column_count |
| C09 | HTML não fechado/mal aninhado | U | reg_C09_html_nesting |
| C10 | Atualização confundida com movimentação | U+P | reg_C10_update_vs_move_manifest |
| C11 | Exclusão/sobrescrita destrutiva sem backup | U | reg_C11_no_destructive_output |
| C12 | Mudança substancial de objetivo mantendo histórico | A | adv_substantial_change_keeps_guid |
| C13 | Parede de cor | U | reg_C13_color_wall |
| C14 | Parágrafos inteiros coloridos | U | reg_C14_colored_paragraph |
| C15 | Valor decisivo sem destaque | A | adv_decisive_value_unhighlighted |
| C16 | Cor por posição, não significado | U | reg_C16_color_from_semantic_only |
| C17 | Complemento competindo com resposta | U | reg_C17_layer_typography |
| C18 | Itens de lista ilegíveis | U | reg_C18_list_one_per_line |
| C19 | Excesso de negrito | U | reg_C19_bold_count_warning |
| C20 | Cabeçalhos/divisórias desnecessários | U | reg_C20_auto_labels_separators |
| C21 | Condições importantes em rodapé | A | adv_essential_in_complement |
| C22 | Tabelas ilegíveis no celular | U (Playwright) | e2e_table_mobile_no_hscroll |
| C23 | Card longo sem objetivo | A | adv_long_card_no_objective |
| C24 | Pergunta com conhecimentos independentes | A | adv_two_objectives |
| C25 | Frente como título vago | U+A | reg_C25_front_interrogative |
| C26 | Explicação que repete a resposta | A | adv_redundant_explanation |
| C27 | Sem sequência lógica | U | test_export_didactic_order |
| C28 | Card correto mas não respondível mentalmente | A+H | adv_unanswerable_card |
| C29 | Fragmentação artificial de lista coesa | A | adv_microcard |
| C30 | Microcards sem contexto | A | adv_microcard_no_context |
| C31 | Fato sem aplicação | A | bench_levels_distribution |
| C32 | Ensina reconhecimento, não recuperação | A | adv_recognition_only |
| C33 | Pistas excessivas | A | adv_front_gives_answer |
| C34 | Verso contradiz a pergunta | A | adv_back_contradicts_front |
| C35 | Termos qualitativos indefinidos | U+A | test_vague_terms_scan |
| C36 | Negativas ambíguas | U+A | test_double_negation_scan |
| C37 | Concentração sem conferir apresentação BR | A | adv_ampoule_vs_final |
| C38 | "Diretriz não existe" por busca falha | A+P | adv_search_fail_inexistence |
| C39 | Norma revogada como vigente | A | adv_revoked_as_current |
| C40 | Fonte estrangeira sem esclarecer BR | A | adv_foreign_silent |
| C41 | Conduta genérica | U+A | test_generic_conduct_scan |
| C42 | Divergência internacional relevante apagada | A | adv_divergence_erased |
| C43 | Referência inventada | U+A | test_citation_requires_source_id |
| C44 | Documento inexistente | A | adv_fake_guideline |
| C45 | Gabarito como fonte clínica | U | test_answer_key_not_evidence |
| C46 | Aceitar correção de outra IA sem verificar | P+A | test_auditor_context_excludes_creator_claims |
| C47 | Fármaco sem disponibilidade BR | A | adv_foreign_drug_as_national |
| C48 | Antídoto sem quando usar/não usar/alvo | A | adv_antidote_incomplete |
| C49 | Cutoff inventado | A | adv_invented_cutoff |
| C50 | Populações misturadas | A | adv_population_mix |
| C51 | Escopo só pelas provas | P | test_generation_requires_objectives |
| C52 | Escopo só pelo conteúdo existente | P | test_independent_map_context_isolation |
| C53 | Tema inteiro ausente ignorado | A | adv_missing_entity |
| C54 | Duplicar entidade contemplada | U+A | test_dedup_layers |
| C55 | Cards específicos no deck-mãe | A | adv_misallocated_card |
| C56 | Questão "fora do tema" com parte no deck | A | adv_out_of_scope_inconsistent |
| C57 | Alternativas incorretas não analisadas | A | adv_only_correct_option |
| C58 | Critérios de destino esquecidos | A | adv_missing_disposition |
| C59 | Seguimento e temporalidade esquecidos | A | adv_missing_temporality |
| C60 | Completude declarada sem conferência | P | test_report_claims_backed_by_task_records |
| C61 | Validação declarada sem script | P | test_report_claims_backed_by_task_records |
| C62 | Cobertura de provas sem acessá-las | P | test_question_coverage_scope |
| C63 | Quantidade = cobertura | P | test_coverage_report_denominator |
| C64 | Limitações não registradas | P | test_schema_requires_limitations |

## Revisor §54

| # | Falha | Tipo | Teste |
|---|---|---|---|
| R01–R03 | Entidades, aspas, notas fantasmas | U | reg_C01–C03 (compartilhados) |
| R04 | Cards truncados na origem não identificados | U | test_legacy_import_reports_bad_rows |
| R05 | Comparação interpretada como HTML | U | reg_C04 |
| R06 | BOM inicial ou residual | U | reg_R06_residual_bom |
| R07 | GUID incorreto | U | test_guid_unique; adv_guid_changed |
| R08 | Correspondência de update não conferida | U | test_validation_module_conferir_match |
| R09 | Duplicadas após importação | U (+Anki) | it_anki_import_disposable |
| R10 | Exclusões ambíguas | U | test_delete_manifest_exact_match |
| R11 | Exclusões recomendadas não aplicadas | U | test_previously_marked_detected |
| R12 | Export desatualizado revertendo correções | U | test_stale_export_detection |
| R13 | Perda de mídia | U | test_media_preserved |
| R14 | Tags alteradas sem justificativa | U | test_tag_change_requires_reason |
| R15 | Update confundido com move | U | reg_C10 |
| R16 | Reenvio sem identificação | U | test_export_versioned_diff |
| R17 | Sobrescrita destrutiva | U | reg_C11 |
| R18–R33 | Falhas científicas (equivalentes a C35–C50 + R32 unidade/concentração, R33 crítica não verificada como confirmada) | A/U | ver C35–C50; adv_unit_swap; test_critical_unverified_quarantine |
| R34 | Auditar só cards existentes | P | test_full_audit_has_five_directions |
| R35 | Sem mapa ideal por subdeck | P | test_map_dimensions_union |
| R36–R46 | Falhas de cobertura (≈ C51–C63, R39 suporte ignorado, R44 materiais não comparados) | A/P | ver C51–C63; adv_support_ignored |
| R47–R59 | Falhas pedagógicas (≈ C23–C34; R58 resposta misturada a comentário; R59 autoavaliação imprecisa) | A | ver C23–C34; adv_self_assessment_ambiguous |
| R60 | Reescrever card bom por estilo | A | adv_good_card_keep |
| R61–R69 | Falhas visuais (≈ C13–C22) | U | ver C13–C22 |
| R70 | Substituição cega de paleta | A | adv_blind_palette_swap |
| R71 | Entregar só sugestões | P | test_corrections_materialized |
| R72 | Não gerar cards obrigatórios | P+A | test_only_required_recommended_generated |
| R73 | Script declarado sem execução | P | test_report_claims_backed_by_task_records |
| R74 | Inspeção visual declarada sem inspeção | P | test_visual_inspection_record_required |
| R75 | Importação declarada sem teste | P | test_import_status_distinct |
| R76 | Não revisar as próprias correções | P | test_modified_card_reaudited |
| R77 | Não simular estado final | P | test_final_state_counts |
| R78 | Porcentagens inventadas | U | test_no_confidence_fields; test_coverage_report_denominator |
| R79 | Média escondendo problema crítico | U | test_release_gate_non_compensatory |
| R80 | Quantidade de alterações = qualidade | P | bench metrics (sem métrica de nº de alterações) |
| R81 | Segunda opinião declarada sem ocorrer | P | test_report_claims_backed_by_task_records |
| R82 | Remover informação válida sem justificativa | A+U | adv_condition_removed; test_regression_coverage_justified |

Na Fase 3 a tabela do Revisor será expandida item a item (hoje agrupada onde é equivalente ao Criador).
