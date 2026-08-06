from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    capture_id: Mapped[int] = mapped_column(ForeignKey("captures.id"), nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="pending")
    error: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
