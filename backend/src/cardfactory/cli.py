"""Linha de comando: `cardfactory serve | migrate | check`."""

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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cardfactory")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="inicia a API e a interface local")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--open", action="store_true", help="abre o navegador")
    s.set_defaults(fn=_serve)
    sub.add_parser("migrate", help="aplica migrações do banco").set_defaults(fn=_migrate)
    sub.add_parser("check", help="verifica documentos normativos e prompts").set_defaults(fn=_check)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
