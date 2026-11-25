from alembic import context

from cardfactory.db.engine import make_engine
from cardfactory.db.models import Base

config = context.config
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # Tabelas FTS5 e suas sombras são criadas por SQL explícito nas migrações.
    return not (type_ == "table" and name and name.startswith("document_section_fts"))


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata, render_as_batch=True,
                          include_object=include_object)
        context.run_migrations()
        return
    engine = make_engine(config.get_main_option("cardfactory.db_path"))
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                          include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
