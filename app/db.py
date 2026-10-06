from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# Şemanın tek kaynağı Alembic'tir (bkz. colEGE README aynı kural) — burada
# `Base.metadata.create_all()` YOK. Geliştirmede de `alembic upgrade head`
# çalıştırılır (SQLite dahil); testler ayrı bir motorda kendi create_all()'unu
# kullanır (bkz. tests/conftest.py), o da yalnız test fixture'ı içindir.
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
