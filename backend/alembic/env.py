from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.database import Base
from app.database import engine as default_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

DATABASE_URL = config.get_main_option("sqlalchemy.url") or None
if DATABASE_URL is None:
    # `str(url)` renders the password as `***`, which yields "password
    # authentication failed" against any real server. SQLite has no password,
    # so this only surfaced once migrations ran against PostgreSQL.
    # The trailing `%` doubling is ConfigParser interpolation: `%%` reads back
    # as a literal `%` in the connection string.
    DATABASE_URL = default_engine.url.render_as_string(hide_password=False).replace("%", "%%")

config.set_main_option("sqlalchemy.url", DATABASE_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
