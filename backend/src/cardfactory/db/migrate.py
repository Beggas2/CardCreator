"""Aplicação programática de migrações Alembic (usada pelo app e pelos testes)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(db_path: Path | str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("cardfactory.db_path", str(db_path))
    return cfg


def upgrade(db_path: Path | str) -> None:
    command.upgrade(alembic_config(db_path), "head")
