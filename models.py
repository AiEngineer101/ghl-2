from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class Event(Base):
    """Raw inbound event payload (webhook, replay, or poll)."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    event_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    opp_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="webhook")
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)

    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="event")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="event")


class Snapshot(Base):
    """Opportunity state at the moment of evaluation. Read-only capture from GHL."""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    opp_id: Mapped[str] = mapped_column(String(64), index=True)
    pipeline_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opp_data: Mapped[dict[str, Any]] = mapped_column(JSON)

    event: Mapped["Event"] = relationship(back_populates="snapshots")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="snapshot")


class Decision(Base):
    """What a handler decided it would have done. `executed` is always False in shadow mode."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id"), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    handler_id: Mapped[str] = mapped_column(String(128), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    target_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    current_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)

    event: Mapped["Event"] = relationship(back_populates="decisions")
    snapshot: Mapped["Snapshot | None"] = relationship(back_populates="decisions")
