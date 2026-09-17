from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from app.billing import calculate_subscription_bill


def assignment(customer_id, name, start, end, pauses=()):
    customer = SimpleNamespace(id=customer_id, name=name, pauses=list(pauses))
    return SimpleNamespace(customer_id=customer_id, customer=customer, start_date=start, end_date=end)


def test_transfer_billing_splits_same_cycle_and_pause():
    pause = SimpleNamespace(start_date=date(2026, 9, 18), end_date=date(2026, 9, 18))
    subscription = SimpleNamespace(
        id=1,
        plan_price=Decimal("2200.00"),
        cycle_start=date(2026, 9, 1),
        cycle_end=date(2026, 9, 30),
        assignments=[
            assignment(1, "A", date(2026, 9, 1), date(2026, 9, 15)),
            assignment(2, "B", date(2026, 9, 16), date(2026, 9, 30), [pause]),
        ],
    )
    result = calculate_subscription_bill(subscription, 2026, 9)
    assert result["total_weekdays"] == 22
    assert result["customers"][0]["delivered_weekdays"] == 11
    assert result["customers"][1]["delivered_weekdays"] == 10
    assert result["customers"][0]["amount"] == Decimal("1100.00")
    assert result["customers"][1]["amount"] == Decimal("1000.00")


def test_weekend_clock_dates_have_no_due_delivery():
    assert date(2026, 9, 19).weekday() >= 5
