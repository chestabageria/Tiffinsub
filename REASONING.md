# Engineering Reasoning

## 1. Problem interpretation and requirements

The product is a weekday tiffin subscription ledger. Owners need customer and subscription administration, phone lookup, pause/resume, prorated billing, notifications, transfer history, and messy CSV import. Customers need a separate authenticated view of only their own service, billing, pauses, and delivery history. The implementation treats T1, T4, and T6 as backend/API requirements; the main owner and customer workflows are also represented in React.

## 2. Architecture decision

React/Vite supplies the landing page, owner workspace, and customer workspace. FastAPI owns REST routing, validation, authentication dependencies, authorization, and response shaping. SQLAlchemy with SQLite provides persistent relational data and foreign keys without requiring a separate database for local evaluation. Billing is isolated in `billing.py` so it can be tested without HTTP. The notification service is a small in-process adapter that writes the outbox table rather than pretending an external provider exists.

## 3. Data model and ownership history

`User` stores login identity, password hash, role, and an optional unique link to `Customer`. `Customer` stores the plan-facing profile and owns pauses and assignments. `Subscription` represents the cycle and plan, while `SubscriptionAssignment` represents who owns each date range in that cycle. This separation preserves history: a transfer changes assignment periods, not the original subscription or customer record. `OutboxNotification` stores delivery events and `ClockState` stores the simulated date.

## 4. Pause/resume design

Pause dates are inclusive. The API validates `end_date >= start_date` and rejects overlap with another active pause for that customer with 409. A one-day pause is a valid one-date range; weekends can be stored but do not remove service or charge because delivery only counts weekdays. Billing intersects pause dates with the requested month and service period. Delivery eligibility and ACTIVE/PAUSED status ignore cancelled pauses.

Resume is date-based because the existing lifecycle is represented by ranges rather than a boolean. It finds pauses active on the real server date and sets `cancelled_at`; it does not rewrite the original dates. That preserves history and makes future billing, status, and delivery calculations ignore the cancelled range. The same rules are used by owner and customer self-service endpoints.

## 5. Billing algorithm

1. Enumerate Monday-Friday dates in the selected calendar month.
2. For each subscription assignment, intersect its dates with the subscription cycle and selected month.
3. Build the set of that customer's active paused weekdays within the month.
4. Subtract paused dates from service dates and count the result as delivered weekdays.
5. Divide the plan price by the total weekdays in the calendar month and multiply by delivered weekdays.
6. Quantize each amount to two decimal places using `Decimal` and `ROUND_HALF_UP`.

The full calendar-month weekday denominator is intentional: a mid-month start reduces delivered days while keeping the denominator stable. For a transferred subscription, every assignment uses the same denominator and receives an amount based on its own delivered dates. Weekday-only delivery matters because weekends must not create either a delivery obligation or a billable service day.

## 6. T1 reasoning

`POST /clock` accepts an optional date, requires an owner, and scans assignments only on weekdays. An assignment is eligible when the simulated date lies within its ownership period and no active pause covers it. The local Notification Service adapter creates an `OutboxNotification`, while `GET /outbox` exposes those records. The `(customer_id, delivery_date)` database uniqueness rule plus the adapter's existing-row lookup makes repeated calls for the same date idempotent in the implemented path. There is no external delivery provider or retry queue.

## 7. T6 reasoning

Transfer must preserve historical ownership so a customer who owned the earlier dates remains billable for those dates and the new customer owns only the later dates. The endpoint requires the transfer date to be inside the original cycle, closes the current assignment on the previous day, and starts a new assignment on the transfer date through the same cycle end. It rejects a missing current assignment and transferring to the existing owner. Billing splits by assignment and applies each customer's pauses. The model's unique assignment-start constraint prevents two assignments from starting on the same date.

## 8. T4 reasoning

CSV handling is deliberately row-oriented. Names and fields are stripped, phone values are normalized to digits, and dates accept ISO format or day/month/year slash format. Ambiguous two-digit hyphen dates are rejected instead of guessed. Missing required values, invalid dates, non-positive prices, and malformed values are rejected with row details. Duplicate phones already in the database or earlier in the same file are deduped. Valid rows are imported with their initial subscription and assignment. The importer commits the batch once and rolls back on an unexpected exception; row validation errors do not abort otherwise valid rows.

## 9. Search, pagination, and sorting

The owner list accepts page, limit, phone, sort field, and order. The backend normalizes the phone filter, restricts sort fields to name, phone, plan price, and subscription start date, and returns total/page metadata plus active and paused counts. The separate search endpoint returns partial phone matches ordered by name. The UI consumes the paged list and provides search, sorting, and previous/next controls.

## 10. Authentication and authorization

Both roles use the same JWT login system. Passwords are hashed with Passlib, tokens expire after 12 hours, and the current user is loaded from the token subject. `owner_only` protects administrative operations. `customer_only` requires a customer role and linked customer row, so customer requests cannot read or mutate another customer. The frontend workspace choice is convenience only; backend dependencies enforce the boundary. The current secret is a development constant, which is a known deployment limitation.

## 11. Customer-side versus owner-side design

The owner sees operational controls and all customers. The customer sees a dashboard assembled from the same database state but scoped by `customer_id`, including plan, status, today's delivery state, billing, pause history, assignment history, and calendar. Customer pause/resume and profile edits call self-service APIs; owner pause/resume uses the corresponding ID-based APIs.

## 12. Error handling and validation

Pydantic validates types, required fields, price positivity, email shape, password length, and date formats. Route logic returns 400 for invalid ranges/months, 401 for invalid credentials/tokens, 403 for the wrong role, 404 for missing resources, and 409 for duplicate or overlapping state. The frontend displays API error details and clears a token after a 401 response.

## 13. Testing strategy and actual edge cases

The backend tests isolate billing with simple customer/assignment objects. They cover a paused weekday plus weekend exclusion, a mid-month subscription start, a transferred cycle split with a pause, and a weekend clock date. The exact checks are `PYTHONPATH=backend python -m pytest -q backend/tests` and `npm --prefix frontend run build`; the repository currently has four passing backend tests and a successful frontend production build. No HTTP integration test suite is present.

## 14. Actual issues encountered

The development transcript records three concrete issues and their fixes. The initial Vite setup command waited for input and was resumed. Frontend requests originally targeted container-local `localhost:8000`, causing browser “Failed to fetch” errors in the Codespace; the frontend was changed to use `/api` with a Vite proxy. Later, an owner customer-creation failure was traced to a stale or customer JWT in the browser; the frontend now clears the token and returns to sign-in after a 401. These are the only development issues recorded here; no additional bugs are inferred.

## 15. Trade-offs, limitations, and future improvements

SQLite and startup compatibility alterations keep local setup small, but they are not a production migration system. The JWT secret is hardcoded, the notification service is local-only, and HTTP integration coverage is limited. The current assignment model creates one initial cycle ending at that month's end, so a production recurring-subscription model would need another lifecycle design. Future improvements are: an external notification provider, payment/receipt reconciliation, and delivery route/staff planning.
