from datetime import date, datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Settlement(Base):
    """A record of one person paying another to clear (part of) the shared balance.

    voided_at NULL = active record; a non-NULL timestamp marks it voided
    (e.g. recorded by mistake) — the balance derivation excludes voided rows.
    """

    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(nullable=False)
    occurred_on: Mapped[date] = mapped_column(nullable=False)
    note: Mapped[Optional[str]] = mapped_column(nullable=True)
    voided_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
