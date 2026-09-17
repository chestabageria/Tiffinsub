import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import ceil
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .auth import create_token, current_user, hash_password, verify_password
from .billing import calculate_monthly_bill, calculate_subscription_bill, weekdays_in_range
from .database import Base, engine, get_db
from .models import ClockState, Customer, OutboxNotification, Subscription, SubscriptionAssignment, SubscriptionPause, User
from .notification_service import notify_customer_due_for_delivery
from .schemas import BillResponse, ClockRequest, CustomerCreate, CustomerPage, CustomerProfileUpdate, CustomerRegisterRequest, CustomerResponse, ImportDetail, ImportReport, LoginRequest, NotificationResponse, PauseCreate, PauseResponse, RegisterRequest, SubscriptionResponse, TokenResponse, TransferRequest

Base.metadata.create_all(bind=engine)


def ensure_customer_account_schema():
    inspector = inspect(engine)
    with engine.begin() as connection:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        pause_columns = {column["name"] for column in inspector.get_columns("subscription_pauses")}
        if "role" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'OWNER'"))
        if "customer_id" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN customer_id INTEGER"))
        if "reason" not in pause_columns:
            connection.execute(text("ALTER TABLE subscription_pauses ADD COLUMN reason TEXT"))
        if "cancelled_at" not in pause_columns:
            connection.execute(text("ALTER TABLE subscription_pauses ADD COLUMN cancelled_at DATETIME"))


ensure_customer_account_schema()
app = FastAPI(title="Tiffin Ledger API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def customer_status(customer: Customer) -> str:
    today = date.today()
    return "PAUSED" if any(not p.cancelled_at and p.start_date <= today <= p.end_date for p in customer.pauses) else "ACTIVE"


def present_customer(customer: Customer) -> CustomerResponse:
    return CustomerResponse(id=customer.id, name=customer.name, phone=customer.phone, address=customer.address, plan_price=customer.plan_price, subscription_start_date=customer.subscription_start_date, status=customer_status(customer))


def clock_date(db: Session) -> date:
    state = db.query(ClockState).first()
    return state.current_date if state else date.today()


def normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def owner_only(user: User = Depends(current_user)) -> User:
    if user.role != "OWNER":
        raise HTTPException(status_code=403, detail="Owner access required")
    return user


def customer_only(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Customer:
    if user.role != "CUSTOMER" or not user.customer_id:
        raise HTTPException(status_code=403, detail="Customer access required")
    customer = db.get(Customer, user.customer_id)
    if not customer:
        raise HTTPException(status_code=403, detail="Customer account is not linked")
    return customer


def parse_month(month: str) -> tuple[int, int]:
    try:
        year, month_number = map(int, month.split("-"))
        date(year, month_number, 1)
        return year, month_number
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Month must be YYYY-MM")


def pause_is_active(pause: SubscriptionPause, on_date: date) -> bool:
    return not pause.cancelled_at and pause.start_date <= on_date <= pause.end_date


def assignment_for_date(customer: Customer, on_date: date):
    return next((item for item in customer.assignments if item.start_date <= on_date <= item.end_date), None)


def pause_view(pause: SubscriptionPause) -> dict:
    return {"id": pause.id, "start_date": pause.start_date, "end_date": pause.end_date, "reason": pause.reason, "status": "RESUMED" if pause.cancelled_at else ("ACTIVE" if pause_is_active(pause, date.today()) else "ENDED")}


def customer_bill(customer: Customer, year: int, month: int) -> dict:
    result = calculate_monthly_bill(customer, year, month)
    return {**result, "customers": [item for item in result["customers"] if item["customer_id"] == customer.id]}


def customer_assignments(customer: Customer) -> list[dict]:
    return [{"subscription_id": item.subscription_id, "customer_id": item.customer_id, "is_current_customer": item.customer_id == customer.id, "start_date": item.start_date, "end_date": item.end_date} for item in sorted(customer.assignments, key=lambda item: item.start_date)]


def create_subscription_for_customer(db: Session, customer: Customer) -> Subscription:
    cycle_end = date(customer.subscription_start_date.year, customer.subscription_start_date.month, 1)
    cycle_end = cycle_end.replace(day=__import__("calendar").monthrange(cycle_end.year, cycle_end.month)[1])
    subscription = Subscription(plan_price=customer.plan_price, cycle_start=customer.subscription_start_date, cycle_end=cycle_end)
    db.add(subscription); db.flush()
    db.add(SubscriptionAssignment(subscription_id=subscription.id, customer_id=customer.id, start_date=customer.subscription_start_date, end_date=cycle_end))
    return subscription


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def api_home():
    return {"name": "Tiffin Ledger API", "docs": "/docs", "health": "/health"}


@app.post("/clock")
def advance_clock(payload: ClockRequest | None = None, db: Session = Depends(get_db), _: User = Depends(owner_only)):
    simulated_date = payload.date if payload and payload.date else date.today()
    state = db.query(ClockState).first()
    if state:
        state.current_date = simulated_date
    else:
        db.add(ClockState(current_date=simulated_date))
    created = []
    notified_keys = set()
    if simulated_date.weekday() < 5:
        for assignment in db.query(SubscriptionAssignment).all():
            eligible = assignment.start_date <= simulated_date <= assignment.end_date and not any(pause_is_active(p, simulated_date) for p in assignment.customer.pauses)
            key = (assignment.customer_id, simulated_date)
            if eligible and key not in notified_keys:
                created.append(notify_customer_due_for_delivery(db, assignment.customer, simulated_date))
                notified_keys.add(key)
    db.commit()
    return {"date": simulated_date, "notified": len(created)}


@app.get("/outbox", response_model=list[NotificationResponse])
def outbox(db: Session = Depends(get_db), _: User = Depends(owner_only)):
    return db.query(OutboxNotification).order_by(OutboxNotification.delivery_date, OutboxNotification.id).all()


@app.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email is already registered")
    user = User(name=payload.name, email=payload.email, password_hash=hash_password(payload.password), role="OWNER")
    db.add(user); db.commit(); db.refresh(user)
    return TokenResponse(access_token=create_token(user.id))


@app.post("/auth/customer/register", response_model=TokenResponse, status_code=201)
def register_customer(payload: CustomerRegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email is already registered")
    customer = db.query(Customer).filter(Customer.phone == normalize_phone(payload.phone)).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer phone is not registered by the owner")
    if db.query(User).filter(User.customer_id == customer.id).first():
        raise HTTPException(status_code=409, detail="Customer account already exists")
    user = User(name=payload.name, email=payload.email, password_hash=hash_password(payload.password), role="CUSTOMER", customer_id=customer.id)
    db.add(user); db.commit(); db.refresh(user)
    return TokenResponse(access_token=create_token(user.id))


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_token(user.id))


@app.get("/customers/me/dashboard")
def customer_dashboard(month: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}$"), customer: Customer = Depends(customer_only), db: Session = Depends(get_db)):
    selected_month = month or date.today().strftime("%Y-%m")
    year, month_number = parse_month(selected_month)
    bill = customer_bill(customer, year, month_number)
    month_start = date(year, month_number, 1)
    month_end = date(year, month_number, __import__("calendar").monthrange(year, month_number)[1])
    today = date.today()
    today_assignment = assignment_for_date(customer, today)
    today_paused = any(pause_is_active(pause, today) for pause in customer.pauses)
    today_notification = db.query(OutboxNotification).filter_by(customer_id=customer.id, delivery_date=today).first()
    calendar = []
    for delivery_date in [month_start + timedelta(days=offset) for offset in range((month_end - month_start).days + 1)]:
        assignment = assignment_for_date(customer, delivery_date)
        if delivery_date.weekday() >= 5:
            state = "WEEKEND"
        elif delivery_date > today:
            state = "FUTURE"
        elif not assignment:
            state = "NO_SERVICE"
        elif any(pause_is_active(pause, delivery_date) for pause in customer.pauses):
            state = "PAUSED"
        else:
            state = "DELIVERED"
        calendar.append({"date": delivery_date, "status": state})
    subscription = today_assignment.subscription if today_assignment else (customer.assignments[0].subscription if customer.assignments else None)
    assignments = customer_assignments(customer)
    return {"customer": present_customer(customer), "subscription": {"id": subscription.id, "plan_price": subscription.plan_price, "cycle_start": subscription.cycle_start, "cycle_end": subscription.cycle_end, "status": subscription.status, "assignments": assignments} if subscription else None, "bill": bill, "pauses": [pause_view(pause) for pause in sorted(customer.pauses, key=lambda item: item.start_date, reverse=True)], "today": {"date": today, "status": "WEEKEND" if today.weekday() >= 5 else "PAUSED" if today_paused else "DELIVERY_DUE" if today_assignment else "NO_SERVICE", "notification": today_notification}, "calendar": calendar}


@app.patch("/customers/me", response_model=CustomerResponse)
def update_customer_profile(payload: CustomerProfileUpdate, customer: Customer = Depends(customer_only), db: Session = Depends(get_db)):
    changes = payload.model_dump(exclude_unset=True)
    if "phone" in changes:
        changes["phone"] = normalize_phone(changes["phone"])
        duplicate = db.query(Customer).filter(Customer.phone == changes["phone"], Customer.id != customer.id).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="Phone number is already registered")
    for key, value in changes.items():
        setattr(customer, key, value)
    db.commit(); db.refresh(customer)
    return present_customer(customer)


@app.post("/customers/me/pause", response_model=PauseResponse, status_code=201)
def pause_current_customer(payload: PauseCreate, customer: Customer = Depends(customer_only), db: Session = Depends(get_db)):
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after start date")
    overlap = db.query(SubscriptionPause).filter(SubscriptionPause.customer_id == customer.id, SubscriptionPause.cancelled_at.is_(None), SubscriptionPause.start_date <= payload.end_date, SubscriptionPause.end_date >= payload.start_date).first()
    if overlap:
        raise HTTPException(status_code=409, detail="Pause overlaps an existing pause")
    pause = SubscriptionPause(customer_id=customer.id, **payload.model_dump())
    db.add(pause); db.commit(); db.refresh(pause)
    return pause


@app.post("/customers/me/resume")
def resume_current_customer(customer: Customer = Depends(customer_only), db: Session = Depends(get_db)):
    today = date.today()
    active = [pause for pause in customer.pauses if pause_is_active(pause, today)]
    for pause in active:
        pause.cancelled_at = datetime.utcnow()
    db.commit()
    return {"message": "Customer resumed", "ended_pauses": len(active)}


@app.get("/customers/me/pauses")
def current_customer_pauses(customer: Customer = Depends(customer_only)):
    return [pause_view(pause) for pause in sorted(customer.pauses, key=lambda item: item.start_date, reverse=True)]


@app.get("/customers/me/subscription")
def current_customer_subscription(customer: Customer = Depends(customer_only)):
    if not customer.assignments:
        return {"subscription": None, "assignments": []}
    subscription = customer.assignments[0].subscription
    return {"subscription": {"id": subscription.id, "plan_price": subscription.plan_price, "cycle_start": subscription.cycle_start, "cycle_end": subscription.cycle_end, "status": subscription.status}, "assignments": customer_assignments(customer)}


@app.get("/customers/me/bill", response_model=BillResponse)
def current_customer_bill(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), customer: Customer = Depends(customer_only)):
    year, month_number = parse_month(month)
    return customer_bill(customer, year, month_number)


@app.get("/customers/me/delivery")
def current_customer_delivery(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), customer: Customer = Depends(customer_only), db: Session = Depends(get_db)):
    year, month_number = parse_month(month)
    month_start = date(year, month_number, 1)
    month_end = date(year, month_number, __import__("calendar").monthrange(year, month_number)[1])
    today = date.today()
    notifications = {item.delivery_date: item for item in db.query(OutboxNotification).filter(OutboxNotification.customer_id == customer.id, OutboxNotification.delivery_date >= month_start, OutboxNotification.delivery_date <= month_end).all()}
    items = []
    for delivery_date in weekdays_in_range(month_start, month_end):
        assignment = assignment_for_date(customer, delivery_date)
        if delivery_date > today:
            state = "FUTURE"
        elif not assignment:
            state = "NO_SERVICE"
        elif any(pause_is_active(pause, delivery_date) for pause in customer.pauses):
            state = "PAUSED"
        else:
            state = "DELIVERED"
        items.append({"date": delivery_date, "status": state, "notification": notifications.get(delivery_date)})
    return {"month": f"{year:04d}-{month_number:02d}", "days": items}


@app.post("/customers", response_model=CustomerResponse, status_code=201)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db), _: User = Depends(owner_only)):
    normalized_phone = normalize_phone(payload.phone)
    if db.query(Customer).filter(Customer.phone == normalized_phone).first():
        raise HTTPException(status_code=409, detail="Phone number is already registered")
    customer_data = payload.model_dump()
    customer_data["phone"] = normalized_phone
    customer = Customer(**customer_data)
    db.add(customer); db.flush(); create_subscription_for_customer(db, customer); db.commit(); db.refresh(customer)
    return present_customer(customer)


@app.get("/customers", response_model=CustomerPage)
def list_customers(page: int = Query(1, ge=1), limit: int = Query(8, ge=1, le=100), phone: str = "", sort_by: str = Query("name"), order: str = Query("asc"), db: Session = Depends(get_db), _: User = Depends(owner_only)):
    sort_map = {"name": Customer.name, "phone": Customer.phone, "plan_price": Customer.plan_price, "subscription_start_date": Customer.subscription_start_date}
    if sort_by not in sort_map:
        raise HTTPException(status_code=400, detail="Invalid sort field")
    query = db.query(Customer)
    if phone:
        query = query.filter(Customer.phone.contains(normalize_phone(phone)))
    column = sort_map[sort_by]
    query = query.order_by(column.desc() if order == "desc" else column.asc())
    total = query.count()
    all_items = query.all()
    items = all_items[(page - 1) * limit:page * limit]
    statuses = [customer_status(item) for item in all_items]
    return CustomerPage(data=[present_customer(item) for item in items], page=page, limit=limit, total=total, total_pages=ceil(total / limit) if total else 0, active_count=statuses.count("ACTIVE"), paused_count=statuses.count("PAUSED"))


@app.get("/customers/search", response_model=list[CustomerResponse])
def search_customers(phone: str = Query(..., min_length=1), db: Session = Depends(get_db), _: User = Depends(owner_only)):
    return [present_customer(item) for item in db.query(Customer).filter(Customer.phone.contains(phone)).order_by(Customer.name).all()]


@app.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: int, db: Session = Depends(get_db), _: User = Depends(owner_only)):
    customer = db.get(Customer, customer_id)
    if not customer: raise HTTPException(status_code=404, detail="Customer not found")
    return present_customer(customer)


@app.post("/customers/{customer_id}/pause", response_model=PauseResponse, status_code=201)
def pause_customer(customer_id: int, payload: PauseCreate, db: Session = Depends(get_db), _: User = Depends(owner_only)):
    customer = db.get(Customer, customer_id)
    if not customer: raise HTTPException(status_code=404, detail="Customer not found")
    if payload.end_date < payload.start_date: raise HTTPException(status_code=400, detail="End date must be on or after start date")
    overlap = db.query(SubscriptionPause).filter(SubscriptionPause.customer_id == customer_id, SubscriptionPause.cancelled_at.is_(None), SubscriptionPause.start_date <= payload.end_date, SubscriptionPause.end_date >= payload.start_date).first()
    if overlap: raise HTTPException(status_code=409, detail="Pause overlaps an existing pause")
    pause = SubscriptionPause(customer_id=customer_id, **payload.model_dump())
    db.add(pause); db.commit(); db.refresh(pause)
    return pause


@app.get("/subscriptions", response_model=list[SubscriptionResponse])
def list_subscriptions(db: Session = Depends(get_db), _: User = Depends(owner_only)):
    return db.query(Subscription).order_by(Subscription.id).all()


@app.get("/subscriptions/{subscription_id}")
def get_subscription(subscription_id: int, db: Session = Depends(get_db), _: User = Depends(owner_only)):
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"id": subscription.id, "plan_price": subscription.plan_price, "cycle_start": subscription.cycle_start, "cycle_end": subscription.cycle_end, "status": subscription.status, "assignments": [{"customer_id": item.customer_id, "customer_name": item.customer.name, "start_date": item.start_date, "end_date": item.end_date} for item in subscription.assignments]}


@app.get("/subscriptions/{subscription_id}/bill")
def get_subscription_bill(subscription_id: int, month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), db: Session = Depends(get_db), _: User = Depends(owner_only)):
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    try:
        year, month_number = map(int, month.split("-")); date(year, month_number, 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Month must be YYYY-MM")
    return calculate_subscription_bill(subscription, year, month_number)


@app.post("/subscriptions/{subscription_id}/transfer")
def transfer_subscription(subscription_id: int, payload: TransferRequest, db: Session = Depends(get_db), _: User = Depends(owner_only)):
    subscription = db.get(Subscription, subscription_id)
    new_customer = db.get(Customer, payload.new_customer_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if not new_customer:
        raise HTTPException(status_code=404, detail="New customer not found")
    if not subscription.cycle_start <= payload.transfer_date <= subscription.cycle_end:
        raise HTTPException(status_code=400, detail="Transfer date must be inside the subscription cycle")
    current = next((item for item in subscription.assignments if item.start_date <= payload.transfer_date <= item.end_date), None)
    if not current:
        raise HTTPException(status_code=409, detail="No current owner exists on the transfer date")
    if current.customer_id == new_customer.id:
        raise HTTPException(status_code=409, detail="New customer already owns the subscription")
    current.end_date = payload.transfer_date - timedelta(days=1)
    db.add(SubscriptionAssignment(subscription_id=subscription.id, customer_id=new_customer.id, start_date=payload.transfer_date, end_date=subscription.cycle_end))
    db.commit()
    return {"message": "Subscription transferred", "subscription_id": subscription.id, "old_customer_id": current.customer_id, "new_customer_id": new_customer.id, "transfer_date": payload.transfer_date}


def parse_import_date(value: str) -> date:
    value = value.strip()
    formats = ["%Y-%m-%d", "%d/%m/%Y"]
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", value):
        day, month, year = map(int, value.split("-"))
        if day <= 12 and month <= 12:
            raise ValueError("Ambiguous date")
        return date(year, month, day)
    for fmt in formats:
        try:
            return __import__("datetime").datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError("Invalid date")


@app.post("/customers/import", response_model=ImportReport)
def import_customers(file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(owner_only)):
    try:
        rows = list(csv.DictReader(io.StringIO(file.file.read().decode("utf-8-sig"))))
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 text")
    imported = 0; deduped = 0; rejected = 0; seen = set(); deduped_details = []; rejected_details = []
    try:
        for row_number, row in enumerate(rows, start=2):
            raw_phone = (row.get("phone") or "").strip()
            phone = normalize_phone(raw_phone)
            name = (row.get("name") or "").strip()
            price = (row.get("plan_price") or "").strip()
            start_value = (row.get("start_date") or row.get("subscription_start_date") or "").strip()
            if not phone:
                rejected += 1; rejected_details.append(ImportDetail(row=row_number, reason="Missing phone")); continue
            if not name:
                rejected += 1; rejected_details.append(ImportDetail(row=row_number, phone=phone, reason="Missing name")); continue
            try:
                plan_price = Decimal(price)
                start_date = parse_import_date(start_value)
                if plan_price <= 0: raise ValueError("Plan price must be positive")
            except (ValueError, ArithmeticError) as error:
                rejected += 1; rejected_details.append(ImportDetail(row=row_number, phone=phone, reason=str(error))); continue
            if phone in seen or db.query(Customer).filter(Customer.phone == phone).first():
                deduped += 1; deduped_details.append(ImportDetail(row=row_number, phone=phone, reason="Duplicate phone")); continue
            seen.add(phone)
            customer = Customer(name=name, phone=phone, address=(row.get("address") or "").strip(), plan_price=plan_price, subscription_start_date=start_date)
            db.add(customer); db.flush(); create_subscription_for_customer(db, customer); imported += 1
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Import transaction failed")
    return ImportReport(imported=imported, deduped=deduped, rejected=rejected, details={"deduped": deduped_details, "rejected": rejected_details})


@app.post("/customers/{customer_id}/resume")
def resume_customer(customer_id: int, db: Session = Depends(get_db), _: User = Depends(owner_only)):
    customer = db.get(Customer, customer_id)
    if not customer: raise HTTPException(status_code=404, detail="Customer not found")
    active = [p for p in customer.pauses if pause_is_active(p, date.today())]
    for pause in active:
        pause.cancelled_at = datetime.utcnow()
    db.commit()
    return {"message": "Customer resumed"}


@app.get("/customers/{customer_id}/pauses", response_model=list[PauseResponse])
def list_pauses(customer_id: int, db: Session = Depends(get_db), _: User = Depends(owner_only)):
    customer = db.get(Customer, customer_id)
    if not customer: raise HTTPException(status_code=404, detail="Customer not found")
    return [pause_view(pause) for pause in db.query(SubscriptionPause).filter(SubscriptionPause.customer_id == customer_id).order_by(SubscriptionPause.start_date.desc()).all()]


@app.get("/customers/{customer_id}/bill", response_model=BillResponse)
def get_bill(customer_id: int, month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), db: Session = Depends(get_db), _: User = Depends(owner_only)):
    customer = db.get(Customer, customer_id)
    if not customer: raise HTTPException(status_code=404, detail="Customer not found")
    try: year, month_number = map(int, month.split("-")); date(year, month_number, 1)
    except ValueError: raise HTTPException(status_code=400, detail="Month must be YYYY-MM")
    return calculate_monthly_bill(customer, year, month_number)
