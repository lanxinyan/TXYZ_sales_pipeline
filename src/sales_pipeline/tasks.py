"""Turn an extracted thread into a to-do item: what kind it is, how urgent,
and the plan of steps that run once you approve.

Steps are either *routine* (Zoho records, Gmail labels - run automatically on
approval) or *gated* (anything a customer will read - prepared as a Gmail
draft and sent only when you press Send)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .config import Settings
from .extract_rules import is_internal
from .models import EmailThread, Order

QUOTE_WORDS = re.compile(r"\b(quote|quotation|RFQ|pricing|price list|报价)\b", re.I)


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def classify(thread: EmailThread, order: Order, s: Settings) -> str:
    """'order', 'quote_request' or 'other'."""
    if order.is_sales_order:
        return "order"
    external = [m for m in thread.messages if m.sender and not is_internal(m.sender, s.internal_domains)]
    if external:
        first = external[0]
        if QUOTE_WORDS.search(f"{thread.subject}\n{first.body[:3000]}"):
            return "quote_request"
    return "other"


def waiting_since(thread: EmailThread, s: Settings) -> str | None:
    """If the newest message is from a customer, they are waiting on us."""
    if not thread.messages:
        return None
    last = thread.messages[-1]
    if last.sender and not is_internal(last.sender, s.internal_domains):
        d = parse_date(last.date)
        return d.isoformat() if d else None
    return None


def prioritize(kind: str, order: Order, issues: list[str], waiting: str | None,
               now: datetime | None = None) -> tuple[int, list[str]]:
    now = now or datetime.now(timezone.utc)
    score = {"order": 50, "quote_request": 40}.get(kind, 0)
    why = []
    if order.total:
        score += min(30, int(order.total / 1000))
        if order.total >= 10000:
            why.append(f"large order ${order.total:,.0f}")
    if waiting:
        hours = (now - datetime.fromisoformat(waiting)).total_seconds() / 3600
        score += min(30, int(hours / 2))
        why.append(f"customer waiting {_age(hours)}")
    if order.customer_status == "new":
        score += 10
        why.append("new customer")
    if order.payment_terms and "prepay" in order.payment_terms.lower():
        why.append("prepayment")
    if issues:
        score += 5
        why.append(f"{len(issues)} thing(s) to check")
    return score, why


def level(score: int) -> str:
    return "high" if score >= 70 else "medium" if score >= 45 else "low"


def _age(hours: float) -> str:
    return f"{hours:.0f}h" if hours < 48 else f"{hours / 24:.0f}d"


def _first_name(order: Order) -> str:
    name = (order.customer.contact_name or "").strip()
    return name.split()[0] if name else "there"


def _items_line(order: Order) -> str:
    return "; ".join(f"{i.product_name} x{i.quantity:g}" for i in order.items) or "your order"


def build_plan(kind: str, order: Order, subject: str, s: Settings, previous: list[dict] | None = None) -> list[dict]:
    """Steps for this item. User choices in `previous` (on/off, edited drafts) are kept."""
    steps: list[dict] = []
    who = order.customer.company or order.customer.email or "customer"
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if kind == "order":
        total = f"${order.total:,.2f}" if order.total else "total unknown"
        steps.append(dict(id="zoho_so", gated=False, enabled=True,
                          title=f"Create Sales Order {order.order_code or '?'} in Zoho",
                          detail=f"{who} · {len(order.items)} item(s) · {total} · "
                                 "Account/Contact/Products found or created, quote PDF attached"))
        steps.append(dict(id="label", gated=False, enabled=True, title="Label email Zoho/Synced", detail=""))
        prepay = bool(order.payment_terms and "prepay" in order.payment_terms.lower())
        steps.append(dict(
            id="confirm", gated=True, enabled=bool(order.customer.email),
            title="Order confirmation to customer",
            draft=dict(to=order.customer.email or "", subject=reply_subject, body=(
                f"Hi {_first_name(order)},\n\n"
                f"Thank you for your order {order.order_code or ''} ({_items_line(order)}). "
                f"The order total is {total}.\n\n"
                + ("As this is a custom service, we will begin once the upfront payment is received; "
                   "our accounting team will send the invoice shortly.\n\n" if prepay else
                   "We will keep you updated on progress and timelines.\n\n")
                + f"{s.email_signature}"))))
        if s.accounting_email:
            steps.append(dict(
                id="accounting", gated=True, enabled=False,
                title="Ask accounting for (prepayment) invoice",
                draft=dict(to=s.accounting_email, subject=f"Invoice request: {order.order_code or subject}", body=(
                    f"Hi,\n\nPlease issue an invoice for order {order.order_code or ''}.\n"
                    f"Customer: {who} <{order.customer.email or ''}>\n"
                    f"Items: {_items_line(order)}\nTotal: {total}\n"
                    + (f"PO: {order.po_number}\n" if order.po_number else "")
                    + (f"Terms: {order.payment_terms}\n" if order.payment_terms else "")
                    + f"\nThanks,\n{s.email_signature}"))))
    elif kind == "quote_request":
        steps.append(dict(id="zoho_contact", gated=False, enabled=bool(order.customer.email),
                          title="Add customer to Zoho (Account + Contact)",
                          detail=f"{who} <{order.customer.email or '?'}>"))
        steps.append(dict(id="label", gated=False, enabled=True, title="Label email Zoho/Quote request", detail=""))
        steps.append(dict(
            id="ack", gated=True, enabled=bool(order.customer.email),
            title="Acknowledge the quote request",
            draft=dict(to=order.customer.email or "", subject=reply_subject, body=(
                f"Hi {_first_name(order)},\n\n"
                "Thank you for your inquiry. We are reviewing the details and will send you a formal "
                "quotation shortly. If you have sample information, quantities or a target timeline, "
                "please share them so we can tailor the quote.\n\n"
                f"{s.email_signature}"))))

    prev = {p["id"]: p for p in previous or []}
    for st in steps:
        st["state"] = "pending"
        p = prev.get(st["id"])
        if p:
            st["enabled"] = p.get("enabled", st["enabled"])
            if p.get("draft") and p.get("draft_edited"):
                st["draft"], st["draft_edited"] = p["draft"], True
            for k in ("state", "result", "draft_id"):
                if k in p:
                    st[k] = p[k]
    return steps
