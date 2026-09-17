from datetime import date
from .models import Customer, OutboxNotification


def notify_customer_due_for_delivery(db, customer: Customer, delivery_date: date) -> OutboxNotification:
    existing = db.query(OutboxNotification).filter_by(customer_id=customer.id, delivery_date=delivery_date).first()
    if existing:
        return existing
    notification = OutboxNotification(
        customer_id=customer.id,
        delivery_date=delivery_date,
        phone=customer.phone,
        message=f"Tiffin delivery due for {customer.name} on {delivery_date.isoformat()}",
    )
    db.add(notification)
    return notification