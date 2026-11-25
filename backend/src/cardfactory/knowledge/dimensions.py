"""As 57 dimensões do mapa ideal: união de C§9 (56 itens) e R§13 (56 itens), ver ADR-0004.

Os códigos 1–56 seguem a ordem do Criador (C§9). O Revisor (R§13) usa nomes próximos para as
mesmas dimensões, não tem "Padrão-ouro" e acrescenta "Integração clínica" (código 57).
"""

DIMENSIONS: dict[int, str] = {
    1: "Definição", 2: "Nomenclatura", 3: "Classificação", 4: "Epidemiologia relevante", 5: "Etiologia",
    6: "Fatores de risco", 7: "Anatomia necessária", 8: "Fisiologia necessária", 9: "Fisiopatologia",
    10: "História natural", 11: "Manifestações típicas", 12: "Manifestações atípicas", 13: "Sinais e sintomas",
    14: "Sinais de gravidade", 15: "Diagnóstico clínico", 16: "Critérios diagnósticos", 17: "Exames laboratoriais",
    18: "Exames de imagem", 19: "Exames funcionais", 20: "Testes confirmatórios", 21: "Padrão-ouro",
    22: "Limitações dos exames", 23: "Falsos positivos e negativos relevantes", 24: "Diagnósticos diferenciais",
    25: "Estratificação de risco", 26: "Escores", 27: "Abordagem inicial", 28: "Tratamento de suporte",
    29: "Tratamento específico", 30: "Tratamento farmacológico", 31: "Tratamento não farmacológico",
    32: "Procedimentos", 33: "Tratamento cirúrgico", 34: "Indicações", 35: "Contraindicações", 36: "Exceções",
    37: "Populações especiais", 38: "Monitoramento", 39: "Resposta terapêutica", 40: "Falha terapêutica",
    41: "Complicações", 42: "Prognóstico", 43: "Destino do paciente", 44: "Critérios de alta", 45: "Seguimento",
    46: "Prevenção", 47: "Profilaxia", 48: "Recorrência", 49: "Associações clássicas",
    50: "Tríades, tétrades e pêntades", 51: "Epônimos relevantes", 52: "Algoritmos diagnósticos",
    53: "Algoritmos terapêuticos", 54: "Pontos de decisão clínica", 55: "Erros comuns de interpretação",
    56: "Diferenças relevantes entre diretrizes", 57: "Integração clínica",
}

# Numeração do Revisor (R§13) → código unificado.
REVISOR_TO_CODE: dict[int, int] = {r: (r if r <= 20 else r + 1) for r in range(1, 56)} | {56: 57}

MAP_STATES = ("APPLICABLE_COVERED", "APPLICABLE_PENDING", "NOT_APPLICABLE", "COVERED_ELSEWHERE", "NOT_VERIFIABLE")

# Estados de cobertura por objetivo (R§14.1, COV-004).
COVERAGE_STATES = ("COMPLETE", "PARTIAL", "INFERABLE", "ABSENT", "INCORRECT", "OUTDATED", "NOT_VERIFIABLE",
                   "COVERED_ELSEWHERE", "NOT_APPLICABLE")
NECESSITY = ("REQUIRED", "RECOMMENDED", "OPTIONAL", "UNNECESSARY")
KNOWLEDGE_LEVELS = ("FACTUAL", "UNDERSTANDING", "APPLICATION")
CLAIM_COMPONENTS = ("INDICATION", "DOSE", "ROUTE", "INTERVAL", "DURATION", "CONTRAINDICATION", "POPULATION",
                    "MECHANISM", "CRITERION", "CUTOFF", "CONDUCT", "DISPOSITION", "OTHER")
CRITICALITY = ("CRITICAL", "HIGH", "NORMAL")
NEGATION_KINDS = ("ABSOLUTE_CI", "RELATIVE_CI", "NO_INDICATION", "RECOMMENDED_AGAINST", "INSUFFICIENT_EVIDENCE",
                  "INDIVIDUALIZE")
VERDICTS = ("CONFIRMED", "INCORRECT", "OUTDATED", "INCOMPLETE", "AMBIGUOUS", "CONTEXT_DEPENDENT", "DIVERGENT",
            "NOT_VERIFIED", "NOT_APPLICABLE")
