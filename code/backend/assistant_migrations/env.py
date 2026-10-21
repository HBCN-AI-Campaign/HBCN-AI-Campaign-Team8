"""Assistant-owned migration history. Never autogenerate against teammate tables."""
from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings

if context.is_offline_mode():
    raise RuntimeError("助手增量迁移需要连接目标数据库，以兼容已运行 create_all 的旧环境。")

engine = create_engine(settings.DATABASE_URL, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, version_table="assistant_alembic_version")
    with context.begin_transaction():
        context.run_migrations()
