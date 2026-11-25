import os
from pathlib import Path

import pytest

from cardfactory.db import Database, make_engine
from cardfactory.db.migrate import upgrade
from cardfactory.finance.budget import FinanceService

# Nenhum teste pode acessar a rede ou usar chave real.
os.environ.pop("OPENROUTER_API_KEY", None)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    path = tmp_path / "test.sqlite"
    upgrade(path)
    return Database(make_engine(path))


@pytest.fixture
def finance(db: Database) -> FinanceService:
    return FinanceService(db)


@pytest.fixture
def budget(finance: FinanceService) -> str:
    finance.set_fx_rate("5.00", margin="0.10")
    return finance.create_budget("PROJECT", "teste", "100", "Projeto teste")
