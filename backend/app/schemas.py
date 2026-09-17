from datetime import date, date as DateType
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6)


class CustomerRegisterRequest(RegisterRequest):
    phone: str = Field(min_length=3, max_length=30)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=3, max_length=30)
    address: str = ""
    plan_price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    subscription_start_date: date


class ClockRequest(BaseModel):
    date: Optional[DateType] = None


class TransferRequest(BaseModel):
    new_customer_id: int
    transfer_date: date


class SubscriptionResponse(BaseModel):
    id: int
    plan_price: Decimal
    cycle_start: date
    cycle_end: date
    status: str


class NotificationResponse(BaseModel):
    id: int
    customer_id: int
    delivery_date: date
    phone: str
    message: str


class ImportDetail(BaseModel):
    row: int
    phone: str | None = None
    reason: str


class ImportReport(BaseModel):
    imported: int
    deduped: int
    rejected: int
    details: dict[str, list[ImportDetail]]


class PauseCreate(BaseModel):
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=500)


class CustomerProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=3, max_length=30)
    address: str | None = None


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str
    address: str
    plan_price: Decimal
    subscription_start_date: date
    status: str


class PauseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    start_date: date
    end_date: date
    reason: str | None = None
    status: str = "ACTIVE"


class CustomerPage(BaseModel):
    data: list[CustomerResponse]
    page: int
    limit: int
    total: int
    total_pages: int
    active_count: int
    paused_count: int


class BillResponse(BaseModel):
    month: str
    plan_price: Decimal
    total_weekdays: int
    paused_weekdays: int
    delivered_weekdays: int
    amount: Decimal
    subscription_id: int | None = None
    customers: list[dict] = []
