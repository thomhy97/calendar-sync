from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CalendarAccount(Base):
    __tablename__ = "calendar_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # 'google' | 'outlook' | 'apple'
    account_email: Mapped[str] = mapped_column(String, nullable=False)
    access_token: Mapped[str] = mapped_column(String, nullable=False)   # chiffré
    refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)  # chiffré
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="calendar_accounts")
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="calendar_account", cascade="all, delete-orphan"
    )
