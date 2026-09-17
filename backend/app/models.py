from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="OWNER")
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    address: Mapped[str] = mapped_column(Text, default="")
    plan_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    subscription_start_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    pauses: Mapped[list["SubscriptionPause"]] = relationship(back_populates="customer", cascade="all, delete-orphan")
    assignments: Mapped[list["SubscriptionAssignment"]] = relationship(back_populates="customer", cascade="all, delete-orphan")


class SubscriptionPause(Base):
    __tablename__ = "subscription_pauses"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    customer: Mapped[Customer] = relationship(back_populates="pauses")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    cycle_start: Mapped[date] = mapped_column(Date)
    cycle_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    assignments: Mapped[list["SubscriptionAssignment"]] = relationship(back_populates="subscription", cascade="all, delete-orphan")


class SubscriptionAssignment(Base):
    __tablename__ = "subscription_assignments"
    __table_args__ = (UniqueConstraint("subscription_id", "start_date", name="uq_assignment_start"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    subscription: Mapped[Subscription] = relationship(back_populates="assignments")
    customer: Mapped[Customer] = relationship(back_populates="assignments")


class OutboxNotification(Base):
    __tablename__ = "outbox_notifications"
    __table_args__ = (UniqueConstraint("customer_id", "delivery_date", name="uq_delivery_notification"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    delivery_date: Mapped[date] = mapped_column(Date, index=True)
    message: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClockState(Base):
    __tablename__ = "clock_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    current_date: Mapped[date] = mapped_column(Date)
