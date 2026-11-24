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
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
