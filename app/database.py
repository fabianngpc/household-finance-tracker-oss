import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.env import load_dot_env

load_dot_env()

DB_PATH = os.environ.get("FINANCE_DB_PATH", "./data/finance.db")
Path(DB_PATH).expanduser().parent.mkdir(parents=True, exist_ok=True)
DB_URL = f"sqlite:///{Path(DB_PATH).expanduser()}"

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},  # required for multi-threaded FastAPI
)


@event.listens_for(engine, "connect")
def enable_wal(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; faster than FULL
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass
