from datetime import date

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FxRate(Base):
    __tablename__ = "fx_rates"

    __table_args__ = (
        UniqueConstraint("base_currency", "quote_currency", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    base_currency: Mapped[str] = mapped_column(nullable=False)   # always "SGD"
    quote_currency: Mapped[str] = mapped_column(nullable=False)  # "USD","MYR","EUR","JPY"
    rate: Mapped[float] = mapped_column(nullable=False)          # units of quote per 1 SGD
    as_of_date: Mapped[date] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(nullable=False, default="frankfurter")
