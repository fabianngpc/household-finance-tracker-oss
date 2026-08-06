from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    color: Mapped[str] = mapped_column(nullable=False)  # hex, e.g. "#F97316"
    icon: Mapped[str] = mapped_column(nullable=False)   # lucide name, e.g. "UtensilsCrossed"
    is_protected: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
