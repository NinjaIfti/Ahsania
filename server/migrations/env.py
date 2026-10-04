from alembic import context
from sqlalchemy import create_engine, pool

from capture.config import Settings
from capture.db import models  # noqa: F401  (registers tables on Base.metadata)
from capture.db.base import Base

config = context.config
url = config.get_main_option("sqlalchemy.url") or Settings().database_url

engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
