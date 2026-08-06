from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OutboundNotification(Base):
    """DB-backed Telegram outbox.

    Decouples "decide to notify" (race-safe, any process: web, bot, worker,
    scheduler) from "deliver" (only the process holding a live Bot instance —
    bot/worker.py drains pending rows).
    """

    __tablename__ = "outbound_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    body: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="pending")  # pending | sending | sent | failed
    error: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
