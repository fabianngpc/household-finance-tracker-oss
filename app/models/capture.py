from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Capture(Base):
    __tablename__ = "captures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    update_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    raw_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False, default="queued")
    confirm_step: Mapped[Optional[str]] = mapped_column(nullable=True)
    amount_str: Mapped[Optional[str]] = mapped_column(nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(nullable=True, default="SGD")
    merchant: Mapped[Optional[str]] = mapped_column(nullable=True)
    expense_date: Mapped[Optional[str]] = mapped_column(nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    expense_id: Mapped[Optional[int]] = mapped_column(ForeignKey("expenses.id"), nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    error: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
