"""Configuração a partir de variáveis de ambiente. Segredos nunca são expostos por esta classe."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# backend/src/cardfactory/config.py → raiz do repositório
REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    port: int = 8765
    host: str = "127.0.0.1"
    worker_concurrency: int = 2
    _has_key: bool = field(default=False, repr=False)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cardfactory.sqlite"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def prompts_dir(self) -> Path:
        return Path(os.environ.get("CARDFACTORY_PROMPTS_DIR", REPO_ROOT / "prompts"))

    @property
    def normative_dir(self) -> Path:
        return REPO_ROOT / "docs" / "normative"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def deck_prefix(self) -> str:
        """AMB-07: prefixo de deck configurável, padrão IGOR."""
        return os.environ.get("CARDFACTORY_DECK_PREFIX", "IGOR")

    @property
    def openrouter_configured(self) -> bool:
        return self._has_key


def load_settings(env_file: Path | None = None) -> Settings:
    if env_file is not None:
        _load_dotenv(env_file)
    data_dir = Path(os.environ.get("CARDFACTORY_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        port=int(os.environ.get("CARDFACTORY_PORT", "8765")),
        worker_concurrency=int(os.environ.get("CARDFACTORY_WORKERS", "2")),
        _has_key=bool(os.environ.get("OPENROUTER_API_KEY")),
    )
