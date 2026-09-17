# Tiffin Ledger

Tiffin Ledger is a local full-stack application for home-style tiffin owners who need to manage weekday subscriptions, pauses, transfers, delivery notifications, and prorated billing. Customers can create a linked account, inspect their plan and bill, pause service, resume service, and view delivery history.

## Users and product surface

- **Tiffin owner/admin:** registers and signs in, creates and imports customers, searches by phone, pages and sorts customers, manages pauses, inspects subscriptions, transfers assignments, runs the delivery clock, and reads the notification outbox.
- **Tiffin customer/user:** registers against an owner-created phone number, signs in, views a customer-scoped dashboard, updates their profile, pauses or resumes service, and views subscription, billing, pause, calendar, and delivery information.

The landing page offers separate owner and customer entry points. The owner workspace is a customer list with status, search, sorting, pagination, add-customer, pause, resume, and pause-history workflows. The customer workspace has dashboard, subscription, pause/resume, billing, delivery-history, and profile views.

## Implemented features

Registration/login, customer management, subscription management, inclusive pause/resume, weekday-only prorated billing, phone search, ACTIVE/PAUSED status, pagination, sorting, owner and customer dashboards, T1 notifications, T6 subscription transfer, and T4 messy CSV import are implemented in the backend. The React UI exposes the main owner and customer workflows; T1, T4, and T6 administrative operations are available through the REST API and FastAPI docs.

## Technology and architecture

- Frontend: React 19, Vite, JavaScript, CSS.
- Backend: FastAPI, SQLAlchemy, Pydantic, PyJWT, Passlib, SQLite.
- Testing: pytest for backend billing and twist calculations; Vite production build for the frontend.

The request path is:

`Frontend -> REST APIs -> FastAPI backend -> SQLite database`

The notification integration is a local adapter: `/clock` calls `notification_service.notify_customer_due_for_delivery`, which writes an `OutboxNotification` row. There is no external SMS/email provider in this repository.

## Database schema

- `users`: owner or customer login identity, hashed password, role, and optional unique `customer_id` link.
- `customers`: name, normalized unique phone, address, monthly plan price, and subscription start date. It owns pause and assignment relationships.
- `subscription_pauses`: inclusive start/end dates, optional reason, creation time, and nullable `cancelled_at` used by resume while preserving history.
- `subscriptions`: plan price, cycle start/end, and status for a subscription cycle.
- `subscription_assignments`: date-bounded ownership of a subscription by a customer. A subscription has one or more assignments after transfer.
- `outbox_notifications`: unique customer/date notification records containing delivery date, phone, and message.
- `clock_state`: the most recently simulated clock date.

Foreign keys connect users to customers, pauses and assignments to customers, assignments to subscriptions, and notifications to customers. Startup creates missing tables and adds the later user/pause columns to an existing SQLite database.

## Business rules and billing

Delivery is Monday through Friday only. A pause is inclusive: every date from `start_date` through `end_date` is paused, but only paused weekdays affect delivery and billing. Overlapping active pauses for one customer are rejected with 409; an end date before a start date is rejected with 400. Resume marks active pauses as cancelled at today's real server date, leaving their original dates and reason visible as history. Cancelled pauses no longer affect status, billing, or delivery.

Each customer creation creates a subscription cycle from the customer's start date through the last day of that calendar month and an initial assignment covering that cycle. A transfer must be inside the cycle. The old assignment ends the day before the transfer date and a new assignment starts on the transfer date, so the original cycle and plan remain intact.

For a requested `YYYY-MM`, `billing.py` first enumerates all Monday-Friday dates in the calendar month. For each assignment it intersects the assignment, subscription cycle, and requested month, removes that customer's active paused weekdays, and counts the remaining delivered weekdays. The amount is:

`plan_price * delivered_weekdays / total_weekdays`

The denominator is all weekdays in the calendar month, including dates before a mid-month subscription start and dates assigned to another customer in a transferred cycle. Each amount is calculated with `Decimal` and rounded to two decimal places using `ROUND_HALF_UP`. The subscription bill returns per-assignment amounts and the total; a customer bill selects that customer's assignment amount. A month with no weekdays returns zero.

## T1: clock and notifications

`POST /clock` accepts an optional `{ "date": "YYYY-MM-DD" }` and requires an owner token. On a weekday it scans subscription assignments and considers an assignment eligible when the date is inside its ownership period and the customer has no active pause covering that date. Eligible customers are passed to the local notification service, which creates an outbox row. The `OutboxNotification` unique constraint is `(customer_id, delivery_date)`, and the adapter returns the existing row on repeat calls, making repeated clock calls for the same customer/date idempotent. Weekends, future assignments, and paused dates are not notified. `GET /outbox` displays the persisted rows to an owner.

## T6: transfer and split billing

`POST /subscriptions/{id}/transfer` accepts `new_customer_id` and `transfer_date`. It validates the subscription, destination customer, cycle bounds, current assignment, and that the destination is not already the current owner. It closes the old ownership period on the previous date and creates the new period through the existing cycle end. `GET /subscriptions/{id}` exposes assignment history. The subscription bill counts each assignment's delivered weekdays separately and calculates each share against the same calendar-month denominator, including customer-specific active pauses.

## T4: messy customer import

`POST /customers/import` accepts a multipart CSV file. The importer strips names/fields, normalizes phone numbers to digits, accepts `YYYY-MM-DD` and `DD/MM/YYYY`, rejects ambiguous `DD-MM-YYYY` values when both day and month are 12 or less, and rejects missing phone/name, invalid dates, non-positive prices, and malformed values. Existing database phones and duplicate phones within the same file are classified as `deduped`; valid new rows are `imported`; invalid rows are `rejected`. The response contains counts and row-level details for deduped and rejected rows. The import commits valid rows as one transaction and rolls back on an unexpected transaction failure.

## Authentication and authorization

Owner registration is `POST /auth/register`; customer registration is `POST /auth/customer/register` using an owner-created phone. Both receive a 12-hour JWT and use `POST /auth/login` for login. Passwords are hashed with Passlib. Owner routes require `role == OWNER`; customer routes require `role == CUSTOMER` and use the token's linked `customer_id`. The JWT secret is currently a development constant in `backend/app/auth.py`; there are no environment variables implemented for it, so production deployment must change that code before use.

## Setup

Prerequisites: Python 3.10+, Node.js/npm, and a shell. No external database or paid service is required. No environment variables are required by the current implementation.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
PYTHONPATH=backend uvicorn app.main:app --reload
```

In another terminal:

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Open the Vite URL shown in the terminal, normally `http://localhost:5173`. The Vite proxy maps `/api` to `http://127.0.0.1:8000`; FastAPI docs are at `http://localhost:8000/docs`. SQLite is created as `tiffin.db` relative to the backend process working directory, normally the repository root with the command above. Tables and compatibility columns are created at backend startup.

## Debugging and troubleshooting

- Use `/health` or `/docs` to confirm FastAPI is running.
- If the frontend reports “Failed to fetch”, keep both processes running and use the Vite URL; browser requests use the `/api` proxy.
- If the API says “Not authenticated” or “Invalid or expired token”, sign in again in the correct workspace. Owner-only actions such as adding customers cannot use a customer token.
- If tests cannot import `app`, run them with `PYTHONPATH=backend` from the repository root.
- Inspect `/outbox` after an owner calls `/clock` to verify T1 eligibility and idempotency.

## REST API

Every endpoint below except `/`, `/health`, `/auth/register`, `/auth/customer/register`, and `/auth/login` requires a bearer token; role restrictions are shown in the last column.

| Method | Endpoint | Purpose | Authentication |
|---|---|---|---|
| GET | `/` | API information | None |
| GET | `/health` | Health check | None |
| POST | `/auth/register` | Register an owner and return JWT | None |
| POST | `/auth/customer/register` | Link a customer account by phone and return JWT | None |
| POST | `/auth/login` | Log in an owner or customer | None |
| POST | `/customers` | Create customer and initial subscription | Owner |
| GET | `/customers` | Paginated, searchable, sortable customer list | Owner |
| GET | `/customers/search` | Partial phone search | Owner |
| GET | `/customers/{customer_id}` | Read one customer | Owner |
| POST | `/customers/{customer_id}/pause` | Add inclusive pause | Owner |
| POST | `/customers/{customer_id}/resume` | Cancel pauses active today | Owner |
| GET | `/customers/{customer_id}/pauses` | Read pause history | Owner |
| GET | `/customers/{customer_id}/bill` | Calculate customer bill | Owner |
| POST | `/customers/import` | Import CSV customers | Owner |
| GET | `/subscriptions` | List subscriptions | Owner |
| GET | `/subscriptions/{subscription_id}` | Read subscription assignments | Owner |
| GET | `/subscriptions/{subscription_id}/bill` | Calculate split subscription bill | Owner |
| POST | `/subscriptions/{subscription_id}/transfer` | Transfer subscription ownership | Owner |
| POST | `/clock` | Simulate date and create eligible notifications | Owner |
| GET | `/outbox` | Read persisted notifications | Owner |
| GET | `/customers/me/dashboard` | Customer profile, status, bill, calendar, and assignments | Customer |
| PATCH | `/customers/me` | Update customer profile | Customer |
| POST | `/customers/me/pause` | Add customer pause | Customer |
| POST | `/customers/me/resume` | Resume today | Customer |
| GET | `/customers/me/pauses` | Read own pause history | Customer |
| GET | `/customers/me/subscription` | Read own subscription history | Customer |
| GET | `/customers/me/bill` | Calculate own bill | Customer |
| GET | `/customers/me/delivery` | Read own weekday delivery history | Customer |

## Demo flow

1. Register and sign in as an owner.
2. Add a customer with a phone, price, and subscription start date.
3. Search, sort, and page through the owner customer list.
4. Add a pause, inspect status/history and the bill, then resume.
5. Register a customer account using that phone and inspect the customer dashboard.
6. Use `/clock` on a weekday, then read `/outbox`; repeat the call to verify no duplicate row.
7. Use the subscription endpoints to transfer ownership and inspect the split bill.
8. Upload a CSV to `/customers/import` and inspect imported, deduped, and rejected counts.

## Testing

Run the actual repository checks from the root:

```bash
PYTHONPATH=backend python -m pytest -q backend/tests
npm --prefix frontend run build
```

The backend suite contains four passing unit tests for weekday/pause billing, mid-month starts, transfer split billing, and weekend clock-date behavior. The frontend production build completes successfully. There are no automated HTTP integration tests in the repository.

## Future features

1. Replace the local outbox adapter with a production notification provider.
2. Add payment collection, receipts, and payment reconciliation.
3. Add route planning and delivery staff assignment.
