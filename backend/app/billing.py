from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP


def weekdays_in_range(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _amount(plan_price: Decimal, delivered: int, total_weekdays: int) -> Decimal:
    if not total_weekdays:
        return Decimal("0.00")
    return (Decimal(plan_price) * Decimal(delivered) / Decimal(total_weekdays)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_subscription_bill(subscription, year: int, month: int) -> dict:
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    total_weekdays = len(weekdays_in_range(month_start, month_end))
    customers = []
    delivered_total = 0
    for assignment in sorted(subscription.assignments, key=lambda item: item.start_date):
        service_start = max(assignment.start_date, subscription.cycle_start, month_start)
        service_end = min(assignment.end_date, subscription.cycle_end, month_end)
        service_days = set(weekdays_in_range(service_start, service_end))
        paused_days = set()
        for pause in assignment.customer.pauses:
            if getattr(pause, "cancelled_at", None):
                continue
            paused_days.update(weekdays_in_range(max(pause.start_date, month_start), min(pause.end_date, month_end)))
        delivered = len(service_days - paused_days)
        delivered_total += delivered
        customers.append({"customer_id": assignment.customer_id, "customer_name": assignment.customer.name, "delivered_weekdays": delivered, "amount": _amount(subscription.plan_price, delivered, total_weekdays)})
    return {"month": f"{year:04d}-{month:02d}", "subscription_id": subscription.id, "plan_price": Decimal(subscription.plan_price).quantize(Decimal("0.01")), "total_weekdays": total_weekdays, "paused_weekdays": total_weekdays - delivered_total, "delivered_weekdays": delivered_total, "amount": _amount(subscription.plan_price, delivered_total, total_weekdays), "customers": customers}


def calculate_monthly_bill(customer, year: int, month: int) -> dict:
    subscriptions = []
    for assignment in getattr(customer, "assignments", []):
        if assignment.subscription not in subscriptions:
            subscriptions.append(assignment.subscription)
    if subscriptions:
        result = calculate_subscription_bill(subscriptions[0], year, month)
        own = next((item for item in result["customers"] if item["customer_id"] == customer.id), None)
        return {**result, "delivered_weekdays": own["delivered_weekdays"] if own else 0, "amount": own["amount"] if own else Decimal("0.00"), "customers": result["customers"]}
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    total_weekdays = len(weekdays_in_range(month_start, month_end))
    service_days = set(weekdays_in_range(max(customer.subscription_start_date, month_start), month_end))
    paused_days = set()
    for pause in customer.pauses:
        if getattr(pause, "cancelled_at", None):
            continue
        paused_days.update(weekdays_in_range(max(pause.start_date, month_start), min(pause.end_date, month_end)))
    paused_days &= service_days
    delivered = len(service_days - paused_days)
    customer_id = getattr(customer, "id", None)
    customer_name = getattr(customer, "name", "Customer")
    return {"month": f"{year:04d}-{month:02d}", "subscription_id": None, "plan_price": Decimal(customer.plan_price).quantize(Decimal("0.01")), "total_weekdays": total_weekdays, "paused_weekdays": len(paused_days), "delivered_weekdays": delivered, "amount": _amount(customer.plan_price, delivered, total_weekdays), "customers": [{"customer_id": customer_id, "customer_name": customer_name, "delivered_weekdays": delivered, "amount": _amount(customer.plan_price, delivered, total_weekdays)}]}
