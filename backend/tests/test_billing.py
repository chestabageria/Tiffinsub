from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from app.billing import calculate_monthly_bill


def test_billing_excludes_weekends_and_pause_days():
    customer = SimpleNamespace(
        subscription_start_date=date(2026, 9, 1),
        plan_price=Decimal("2200.00"),
        pauses=[SimpleNamespace(start_date=date(2026, 9, 10), end_date=date(2026, 9, 12))],
    )
    result = calculate_monthly_bill(customer, 2026, 9)
    assert result["total_weekdays"] == 22
    assert result["paused_weekdays"] == 2
    assert result["delivered_weekdays"] == 20
    assert result["amount"] == Decimal("2000.00")


def test_mid_month_subscription_only_counts_service_days():
    customer = SimpleNamespace(subscription_start_date=date(2026, 9, 15), plan_price=Decimal("2200.00"), pauses=[])
    result = calculate_monthly_bill(customer, 2026, 9)
    assert result["delivered_weekdays"] == 12
    assert result["amount"] == Decimal("1200.00")
