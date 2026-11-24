"""Linha de comando: `cardfactory serve | migrate | backup | check | experimento`."""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from cardfactory.config import REPO_ROOT, load_settings

LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from cardfactory.api.app import create_app

    if args.host not in LOCAL_HOSTS:
        print("Recusado: o CardFactory só escuta em 127.0.0.1 (SEC-004).", file=sys.stderr)
        return 2
    settings = load_settings(REPO_ROOT / ".env")
    port = args.port or settings.port
    url = f"http://127.0.0.1:{port}/"
    print(f"CardFactory em {url}  (dados: {settings.data_dir})")
    print("OpenRouter:", "chave configurada" if settings.openrouter_configured else "sem chave (somente simulações)")
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(settings), host=args.host, port=port, log_level="info")
    return 0


def _migrate(_args: argparse.Namespace) -> int:
    from cardfactory.db.migrate import upgrade

    settings = load_settings(REPO_ROOT / ".env")
    upgrade(settings.db_path)
    print(f"Banco atualizado: {settings.db_path}")
    return 0


def _backup(_args: argparse.Namespace) -> int:
    """Cópia consistente do banco (API de backup do SQLite; funciona com o app aberto)."""
    import sqlite3
    from datetime import datetime

    settings = load_settings(REPO_ROOT / ".env")
    if not settings.db_path.is_file():
        print("Nenhum banco para copiar.", file=sys.stderr)
        return 1
    dest_dir = settings.data_dir / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"cardfactory-{datetime.now():%Y%m%d-%H%M%S}.sqlite"
    src = sqlite3.connect(settings.db_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    print(f"Backup gravado em {dest}")
    return 0


def _check(_args: argparse.Namespace) -> int:
    """Verificações locais sem rede: hashes normativos e cobertura de prompts."""
    import hashlib

    from cardfactory.db import Database, make_engine
    from cardfactory.db.migrate import upgrade
    from cardfactory.prompts.registry import PromptRegistry

    settings = load_settings(REPO_ROOT / ".env")
    ok = True
    sums = (settings.normative_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    for line in filter(None, sums):
        digest, name = line.split(None, 1)
        name = name.lstrip("*")
        real = hashlib.sha256((settings.normative_dir / name).read_bytes()).hexdigest()
        good = real == digest
        ok &= good
        print(f"{'OK ' if good else 'ERRO'} {name}")
    upgrade(settings.db_path)
    reg = PromptRegistry(Database(make_engine(settings.db_path)), settings.prompts_dir, settings.normative_dir)
    reg.import_library()
    for role, missing in reg.coverage_report().items():
        ok &= not missing
        print(f"{'OK ' if not missing else 'ERRO'} prompt {role}" + (f": faltam {missing}" if missing else ""))
    return 0 if ok else 1


def _experiment(args: argparse.Namespace) -> int:
    """Sincroniza o catálogo (gratuito) e grava a proposta da Etapa 1. Não faz chamada de geração."""
    import asyncio
    from decimal import Decimal

    from cardfactory.benchmark import experiment
    from cardfactory.db import Database
    from cardfactory.db.engine import make_engine
    from cardfactory.db.migrate import upgrade
    from cardfactory.finance.budget import FinanceService
    from cardfactory.providers.gateway import LLMGateway
    from cardfactory.providers.openrouter import OpenRouterProvider

    settings = load_settings(REPO_ROOT / ".env")
    upgrade(settings.db_path)
    db = Database(make_engine(settings.db_path))
    finance = FinanceService(db)
    if args.cambio:
        finance.set_fx_rate(args.cambio, source="cli")
    if not args.sem_sincronizar:
        if not settings.openrouter_configured:
            print("Configure OPENROUTER_API_KEY no .env (o catálogo não gera cobrança).", file=sys.stderr)
            return 1
        n = asyncio.run(LLMGateway(db, finance, OpenRouterProvider()).sync_catalog())
        print(f"Catálogo sincronizado: {n} modelos.")
    caps = {"creator": Decimal(args.teto), "auditor_scientific": Decimal(args.teto)} if args.teto else None
    p = experiment.plan_from_db(db, finance, budget_brl=Decimal(args.orcamento), caps=caps)
    out_dir = settings.data_dir / "experimento"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = experiment.to_markdown(p)
    (out_dir / "etapa1-plano.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"Gravado em {out_dir / 'etapa1-plano.md'}")
    return 0


def _etapa1(args: argparse.Namespace) -> int:
    """Executa um passo da Etapa 1 com modelos reais. Cada passo grava o estado em data/experimento/etapa1.json."""
    import asyncio
    import json

    from cardfactory.benchmark import experiment_run as er
    from cardfactory.db import Database
    from cardfactory.db.engine import make_engine
    from cardfactory.db.migrate import upgrade
    from cardfactory.finance.budget import FinanceService
    from cardfactory.providers.openrouter import OpenRouterProvider

    settings = load_settings(REPO_ROOT / ".env")
    upgrade(settings.db_path)
    db = Database(make_engine(settings.db_path))
    path = settings.data_dir / "experimento" / "etapa1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def save() -> None:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if args.passo == "orcamento":
        if not (args.cambio and args.autorizado_por and args.limite):
            print("Informe --cambio, --limite e --autorizado-por.", file=sys.stderr)
            return 2
        fin = FinanceService(db)
        fin.set_fx_rate(args.cambio, source="cli")
        bid = fin.create_budget("EXPERIMENT", "etapa1", args.limite, f"Etapa 1 (até R$ {args.limite})")
        state["budget_id"] = bid
        state["authorization_id"] = fin.authorize_spend(bid, args.limite, args.autorizado_por, args.nota or "")
        if settings.openrouter_configured:  # catálogo com preços: base da estimativa de cada chamada (gratuito)
            from cardfactory.providers.gateway import LLMGateway

            state["catalog_models"] = asyncio.run(LLMGateway(db, fin, OpenRouterProvider()).sync_catalog())
        save()
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    if not settings.openrouter_configured:
        print("OpenRouter não configurada (OPENROUTER_API_KEY ou OPENROUTER_AUTH_VIA_PROXY=1).", file=sys.stderr)
        return 1
    if "budget_id" not in state:
        print("Rode o passo 'orcamento' antes.", file=sys.stderr)
        return 1
    env = er.build_env(settings, db, OpenRouterProvider())
    lst = [m.strip() for m in (args.modelos or "").split(",") if m.strip()]
    if args.passo == "preparar":
        ws = {"max_results": args.busca_web} if args.busca_web else None
        out = asyncio.run(er.prepare(env, theme=args.tema, support_model=args.apoio, budget_id=state["budget_id"],
                                     web_search=ws, web_search_price_usd=args.preco_busca,
                                     research_model=args.pesquisador))
        state["prepare"] = out
        state["objective_ids"] = er.pick_objectives(env, out["production_id"], args.objetivos)
    elif args.passo == "completo":
        models = dict(kv.split("=", 1) for kv in lst)  # ETAPA=modelo; "default" cobre as demais
        out = asyncio.run(er.full_run(env, theme=args.tema, models=models, budget_id=state["budget_id"],
                                      target_cards=args.cards))
        state.setdefault("full", []).append(out)
    elif args.passo == "a":
        out = asyncio.run(er.round_a(env, pilot_production_id=state["prepare"]["production_id"],
                                     objective_ids=state["objective_ids"], creators=lst, auditor=args.apoio,
                                     budget_id=state["budget_id"]))
        state.setdefault("round_a", []).append(out)
    else:
        out = asyncio.run(er.round_b(env, auditors=lst, budget_id=state["budget_id"],
                                     actor=args.autorizado_por or "cli"))
        state.setdefault("round_b", []).append(out)
    state["budget"] = FinanceService(db).status(state["budget_id"]).as_dict()
    save()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cardfactory")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="inicia a API e a interface local")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--open", action="store_true", help="abre o navegador")
    s.set_defaults(fn=_serve)
    sub.add_parser("migrate", help="aplica migrações do banco").set_defaults(fn=_migrate)
    sub.add_parser("backup", help="copia o banco para data/backups").set_defaults(fn=_backup)
    sub.add_parser("check", help="verifica documentos normativos e prompts").set_defaults(fn=_check)
    e = sub.add_parser("experimento", help="Etapa 1: candidatos e custo estimado (sem chamadas pagas)")
    e.add_argument("--orcamento", default="15", help="limite em reais (padrão 15)")
    e.add_argument("--teto", default=None, help="preço máximo de saída em US$ por milhão de tokens")
    e.add_argument("--cambio", default=None, help="cadastra a cotação USD→BRL antes de estimar")
    e.add_argument("--sem-sincronizar", action="store_true", help="usa o catálogo já salvo")
    e.set_defaults(fn=_experiment)
    t = sub.add_parser("etapa1", help="Etapa 1 com modelos reais: orcamento | preparar | a | b")
    t.add_argument("passo", choices=["orcamento", "preparar", "completo", "a", "b"])
    t.add_argument("--cambio")
    t.add_argument("--limite", help="limite em reais")
    t.add_argument("--autorizado-por")
    t.add_argument("--nota")
    t.add_argument("--tema")
    t.add_argument("--apoio", help="modelo de pesquisa/extração/planejamento e auditor fixo")
    t.add_argument("--modelos", help="lista separada por vírgulas (criadores na rodada A, auditores na B)")
    t.add_argument("--objetivos", type=int, default=5)
    t.add_argument("--cards", type=int, default=8, help="meta de cards da produção completa")
    t.add_argument("--pesquisador", help="modelo só da pesquisa de fontes (padrão: o de apoio)")
    t.add_argument("--busca-web", type=int, default=0, help="resultados de busca na pesquisa (0 = sem busca)")
    t.add_argument("--preco-busca", default=None, help="US$ por busca, para a estimativa")
    t.set_defaults(fn=_etapa1)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
