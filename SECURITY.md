# SECURITY

| Ameaça | Controle | Teste |
|---|---|---|
| Exposição da chave de API | Chave só via variável de ambiente ou Windows Credential Manager (`keyring`); nunca enviada ao frontend; filtro de logs redige padrões `sk-or-…` e o valor configurado; exportações verificadas | `test_secret_redaction`, `test_no_secret_in_exports`, `test_api_never_returns_key` |
| Commits com segredos | `.env` no `.gitignore`; `.env.example` sem valores; verificação na CI | `test_env_example_has_no_values` |
| Acesso remoto à API local | Bind exclusivo em `127.0.0.1`; verificação de `Host`/`Origin` contra DNS rebinding | `test_bind_localhost`, `test_rejects_foreign_origin` |
| Prompt injection documental | Conteúdo externo delimitado como `untrusted`; modelos não recebem ferramentas que alterem estado; toda ação é executada por código a partir de saída estruturada validada | `adv_prompt_injection_pdf` |
| HTML malicioso / scripts em cards | Modelo envia texto puro; renderizador escapa tudo; validador com allowlist de tags/atributos; bloqueio de `on*`, `javascript:`, `url()`, `@import`, mídia externa | `adv_script_injection`, `test_html_allowlist` |
| SSRF | Fetcher só `http(s)`; resolve DNS e bloqueia IPs privados, loopback, link-local, multicast; revalida a cada redirecionamento; limite de tamanho e tempo; só portas 80/443 e tipos HTML/texto/PDF. Risco residual: troca de DNS entre a validação e a conexão (rebinding), aceitável para app local de usuário único. Opção `CARDFACTORY_FETCH_VIA_PROXY=1` (desligada por padrão, só com proxy de saída configurado): se o nome não resolve localmente, quem decide o destino é o proxy, que só alcança hosts públicos permitidos; IP literal privado continua bloqueado | `tests/unit/test_fetch.py` |
| Arquivos grandes | Limite configurável de upload/download (padrão 50 MB) e de páginas por PDF | `test_upload_limits` |
| Ações destrutivas | Não existe exclusão de notas; operações de banco destrutivas (reset) exigem confirmação explícita na UI e fazem backup | `test_no_destructive_output` |
| Alteração de normativos/prompts | `docs/normative` imutável (hash); prompts versionados append-only | `test_normative_docs_hash`, `test_prompt_version_immutable` |
| Gasto não autorizado | Provedor real exige autorização de gasto ativa + reserva de orçamento | `test_real_provider_requires_authorization` |
| Dados pessoais | Nenhum dado pessoal coletado além do nome do revisor; cabeçalhos de API genéricos | revisão |
| Direitos de uso | Fontes com licença registrada; trechos autorizados curtos; alerta de similaridade com material de terceiros | `test_rights_flag` |

Reportar vulnerabilidades ao proprietário do repositório.
