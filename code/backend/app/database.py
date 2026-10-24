"""SQLAlchemy 引擎 / 会话 / Base。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

# SQLite 需要 check_same_thread=False 才能在 FastAPI 多线程下工作；
# PostgreSQL 不需要该参数。
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}

# 连接池：PostgreSQL 下限制并发连接数（RDS 账号上限 30，应用池建议 5–10），
# 并开启 pool_pre_ping 防止 RDS 空闲断链导致偶发 500；SQLite 不用连接池参数。
_engine_kwargs = dict(connect_args=connect_args, echo=settings.DEBUG, future=True)
if not _is_sqlite:
    _engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=settings.DB_POOL_PRE_PING,
    )

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    """FastAPI 依赖：按请求提供一个数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
