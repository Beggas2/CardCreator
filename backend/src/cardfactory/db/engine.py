"""Engine SQLite com WAL, chaves estrangeiras e transações IMMEDIATE para escrita atômica."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def make_engine(db_path: Path | str) -> Engine:
    url = "sqlite://" if str(db_path) == ":memory:" else f"sqlite:///{Path(db_path).as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # pragma: no cover - executado pelo driver
        # Controle manual de transações: permite BEGIN IMMEDIATE explícito.
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    @event.listens_for(engine, "begin")
    def _begin(conn):  # pragma: no cover
        mode = conn.info.pop("begin_mode", "DEFERRED")
        conn.exec_driver_sql(f"BEGIN {mode}")

    return engine


class Database:
    def __init__(self, engine: Engine):
        self.engine = engine

    @contextmanager
    def _tx(self, mode: str) -> Iterator[Session]:
        with self.engine.connect() as conn:
            conn.info["begin_mode"] = mode
            with conn.begin():
                s = Session(bind=conn, expire_on_commit=False)
                try:
                    yield s
                    s.flush()
                finally:
                    s.close()

    def session(self) -> contextmanager:
        """Transação DEFERRED (leituras e escritas simples)."""
        return self._tx("DEFERRED")

    def write(self) -> contextmanager:
        """BEGIN IMMEDIATE: obtém o lock de escrita no início (reservas de orçamento, leases)."""
        return self._tx("IMMEDIATE")
