from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    link_code: Mapped[Optional[str]] = mapped_column(unique=True, nullable=True)
    link_code_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
