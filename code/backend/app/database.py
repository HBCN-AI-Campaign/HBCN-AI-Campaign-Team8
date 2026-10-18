"""SQLAlchemy 引擎 / 会话 / Base。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

# SQLite 需要 check_same_thread=False 才能在 FastAPI 多线程下工作；
# PostgreSQL 不需要该参数。
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=settings.DEBUG,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    """FastAPI 依赖：按请求提供一个数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
